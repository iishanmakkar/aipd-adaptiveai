import { engineChat } from './engine';
import { runAgent } from './agent';
import type { AgentEvent, AgentResult } from './agent';
import { extractJson } from './gemini';
import type { GeminiMessage } from './gemini';
import type { Settings, UserProfile } from './profile';

/**
 * Orchestration layer: one voice goal becomes a fused plan → routed execution → verification.
 *
 * One fused plan call with a small token budget breaks the goal into steps, then the
 * agent executes them. Single fused plan call — no separate classify step.
 */

export type OrchestratorEvent =
  | { type: 'plan'; text: string; steps: PlannedStep[] }
  | { type: 'status'; text: string }
  | { type: 'speak'; text: string }
  | { type: 'agent-event'; event: AgentEvent; stepIndex: number }
  | { type: 'done'; summary: string };

export type PlannedStepKind = 'device' | 'answer';

export type PlannedStep = {
  kind: PlannedStepKind;
  instruction: string;
};

export type OrchestratorResult = {
  summary: string;
  planSteps: number;
  executed: number;
  engineNotes: string[];
};

/** Gemini plan/verify calls get a hard latency ceiling — a stalled plan becomes a direct run. */
const PLAN_TIMEOUT_MS = 20000;
const VERIFY_TIMEOUT_MS = 15000;
const MAX_AGENT_STEPS = 3;

const PLAN_SYSTEM = [
  'You are the orchestrator of a phone assistant for a blind or low-vision user.',
  'Break the goal into the minimum number of steps. Device actions that happen on the same',
  'screen must be ONE step. Merge related actions; never split a single form into two steps.',
  'Reply with ONLY JSON: {"steps":[{"kind":"device"|"answer","instruction":"..."}],',
  '"spoken":"one friendly sentence acknowledging the goal"}.',
  'kind "device" = an agent operates apps on the phone. kind "answer" = pure information',
  'reply, no phone actions. Maximum 3 steps. The user is blind — the spoken line is what',
  'they hear first, make it short.',
].join(' ');

const VERIFY_SYSTEM = [
  'You verify whether a phone assistant completed the user goal. Reply with ONLY JSON:',
  '{"ok":true,"spoken":"one short sentence telling the blind user it is done"} or',
  '{"ok":false,"spoken":"one short sentence saying honestly what is still missing"}.',
].join(' ');

function planTimeoutSignal(signal: AbortSignal | undefined, ms: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort, { once: true });
  return {
    signal: controller.signal,
    cancel: () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    },
  };
}

/** Parse and sanity-check the plan JSON; anything unusable degrades to one direct step. */
function parsePlan(raw: string, goal: string): { steps: PlannedStep[]; spoken: string } {
  const parsed = extractJson(raw) as { steps?: unknown; spoken?: unknown } | null;
  const rawSteps = Array.isArray(parsed?.steps) ? parsed!.steps : [];
  const steps: PlannedStep[] = [];
  for (const item of rawSteps.slice(0, MAX_AGENT_STEPS)) {
    if (!item || typeof item !== 'object') continue;
    const rawKind = (item as PlannedStep).kind;
    if (rawKind !== 'answer' && rawKind !== 'device') continue;
    const instruction = String((item as PlannedStep).instruction ?? '').trim();
    if (instruction) steps.push({ kind: rawKind, instruction });
  }
  if (steps.length === 0) {
    // Degrade honestly: run the goal directly rather than inventing a plan.
    return { steps: [{ kind: 'device', instruction: goal }], spoken: `Starting: ${goal}` };
  }
  const spoken = typeof parsed?.spoken === 'string' && parsed.spoken.trim() ? parsed.spoken.trim() : `Starting: ${goal}`;
  return { steps, spoken };
}

async function planCall(
  messages: GeminiMessage[],
  opts: { geminiApiKey: string; settings: Settings; signal?: AbortSignal; timeoutMs: number },
): Promise<string> {
  const { signal, cancel } = planTimeoutSignal(opts.signal, opts.timeoutMs);
  try {
    const result = await engineChat({
      geminiApiKey: opts.geminiApiKey,
      settings: { ...opts.settings, temperature: 0 },
      messages,
      // Gemini 2.5+ spends 422–940 tokens on hidden thoughts before answering (measured),
      // and thinking is billed against maxOutputTokens — 1024 returned finishReason
      // MAX_TOKENS with the plan JSON cut mid-string on 4 of 5 calls, which parsePlan
      // then rejected, silently degrading every run to a direct run with no plan.
      maxTokensOverride: 3072,
      signal,
    });
    return result.text;
  } finally {
    cancel();
  }
}

export async function runOrchestrated(opts: {
  goal: string;
  geminiApiKey: string;
  settings: Settings;
  profile: UserProfile;
  onEvent: (event: OrchestratorEvent) => void;
  signal?: AbortSignal;
}): Promise<OrchestratorResult> {
  const { goal, geminiApiKey, settings, profile, onEvent, signal } = opts;
  const engineNotes: string[] = [];
  const started = Date.now();

  if (signal?.aborted) {
    return { summary: 'Stopped before starting.', planSteps: 0, executed: 0, engineNotes };
  }

  // 1) Fused plan — one Gemini call, ~300 token budget, temperature 0. If it fails
  // we degrade to running the goal directly instead of dying.
  onEvent({ type: 'status', text: 'Planning…' });
  let plan: { steps: PlannedStep[]; spoken: string };
  const canPlan = Boolean(geminiApiKey);
  if (!canPlan) {
    plan = { steps: [{ kind: 'device', instruction: goal }], spoken: `Starting: ${goal}` };
    engineNotes.push('plan skipped (no Gemini key) — direct run');
  } else try {
    const raw = await planCall(
      [
        { role: 'system', content: PLAN_SYSTEM },
        { role: 'user', content: `User goal: "${goal}"` },
      ],
      { geminiApiKey, settings, signal, timeoutMs: PLAN_TIMEOUT_MS },
    );
    plan = parsePlan(raw, goal);
    // parsePlan degrades to a single direct step when the JSON did not parse — claiming
    // "planned by gemini" for that case hid the fact that planning never worked.
    if (extractJson(raw)) {
      engineNotes.push('planned by gemini');
    } else {
      engineNotes.push('plan response unparseable — direct run');
    }
  } catch (err) {
    if (signal?.aborted) {
      return { summary: 'Stopped.', planSteps: 0, executed: 0, engineNotes };
    }
    plan = { steps: [{ kind: 'device', instruction: goal }], spoken: `Starting: ${goal}` };
    const msg = err instanceof Error ? err.message : String(err);
    engineNotes.push(`plan degraded to direct run: ${msg.slice(0, 80)}`);
  }
  if (!plan) plan = { steps: [{ kind: 'device', instruction: goal }], spoken: `Starting: ${goal}` };

  onEvent({ type: 'plan', text: plan.spoken, steps: plan.steps });
  if (settings.speakResponses) onEvent({ type: 'speak', text: plan.spoken });

  // 2) Execute. Device steps run sequentially (one screen, one agent). Answer steps resolve
  // inline through the normal engine routing.
  let executed = 0;
  const results: string[] = [];
  for (let i = 0; i < plan.steps.length; i++) {
    if (signal?.aborted) break;
    const step = plan.steps[i];
    onEvent({ type: 'status', text: `Step ${i + 1} of ${plan.steps.length}: ${step.instruction}` });

    if (step.kind === 'answer') {
      try {
        const res = await engineChat({
          geminiApiKey,
          settings,
          messages: [
            {
              role: 'system',
              content:
                'You answer for a blind user over speech. Be accurate and under 60 words. Say "not sure" rather than inventing.',
            },
            { role: 'user', content: step.instruction },
          ],
          signal,
          // Answer steps had no ceiling and inherited chat()'s 120 s default — a stalled
          // request left the user hearing "Step 1 of 2: …" then silence for two minutes.
          timeoutMs: 45000,
        });
        results.push(res.text);
        engineNotes.push(`step ${i + 1} answered by ${res.engine} in ${res.ms} ms`);
        onEvent({ type: 'speak', text: res.text });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        results.push(`Could not answer: ${msg}`);
        engineNotes.push(`step ${i + 1} answer failed: ${msg.slice(0, 80)}`);
        onEvent({ type: 'speak', text: `I could not answer that part: ${msg}` });
      }
      executed += 1;
      continue;
    }

    // Device step: the agent loop owns the screen for this sub-goal.
    const toFailure = (err: unknown): AgentResult => ({
      status: 'failed',
      summary: err instanceof Error ? err.message : String(err),
      steps: 0,
    });
    const result: AgentResult = await new Promise<AgentResult>((resolve) => {
      // Both handlers must be total: a null/undefined rejection used to throw on
      // `(err as Error).message` INSIDE the handler, so resolve never ran, the promise
      // never settled, and runOrchestrated never returned — the UI stayed
      // "Busy — wait for the current task to finish." forever with no way out.
      void runAgent({
        instruction: step.instruction,
        geminiApiKey,
        settings,
        profile,
        onEvent: (event) => onEvent({ type: 'agent-event', event, stepIndex: i }),
        signal,
      })
        .then(resolve, (err) => resolve(toFailure(err)))
        .catch((err) => resolve(toFailure(err)));
    });
    executed += 1;
    // Strip the status prefix for the spoken summary (keep it only internally for verify).
    results.push(result.summary);
    if (result.status !== 'completed') {
      // A failed device step usually means the remaining steps build on it — stop and tell
      // the truth instead of burning steps on a broken premise.
      if (i < plan.steps.length - 1) {
        engineNotes.push(`step ${i + 1} ${result.status}; remaining steps skipped`);
        break;
      }
    }
  }

  // 3) Verify — only when more than one step ran (a single step is already verified by its
  // own completion status). Small token budget, hard timeout.
  let summary = results.join(' ');
  if (plan.steps.length > 1 && !signal?.aborted && results.length > 0) {
    onEvent({ type: 'status', text: 'Checking the result…' });
    try {
      const raw = await planCall(
        [
          { role: 'system', content: VERIFY_SYSTEM },
          {
            role: 'user',
            content: `Goal: "${goal}"\nStep outcomes:\n${results.map((r, i) => `${i + 1}. ${r}`).join('\n')}`,
          },
        ],
        { geminiApiKey, settings, signal, timeoutMs: VERIFY_TIMEOUT_MS },
      );
      const verdict = extractJson(raw) as { ok?: boolean; spoken?: string } | null;
      if (verdict && typeof verdict.spoken === 'string' && verdict.spoken.trim()) {
        summary = verdict.spoken.trim();
        engineNotes.push(`verdict ${verdict.ok === false ? 'not ok' : 'ok'} by gemini`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      engineNotes.push(`verify skipped: ${msg.slice(0, 60)}`);
    }
  }

  onEvent({ type: 'done', summary });
  if (settings.speakResponses && summary) onEvent({ type: 'speak', text: summary });
  console.log(`[orchestrator] goal done in ${Date.now() - started} ms notes=${engineNotes.join('; ')}`);
  return { summary, planSteps: plan.steps.length, executed, engineNotes };
}
