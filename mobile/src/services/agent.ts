import { assist, ensureMicPermission, ensureNotificationPermission, subscribeVoice } from '../native/assist';
import type { ScreenTree } from '../native/assist';
import { engineChat } from './engine';
import { extractJson } from './gemini';
import type { GeminiMessage } from './gemini';
import type { Settings, TaskRecord, UserProfile } from './profile';

export type AgentEvent =
  | { type: 'status'; text: string }
  | { type: 'thinking'; step: number }
  | { type: 'action'; step: number; action: string; args: Record<string, any>; label: string }
  | { type: 'observation'; step: number; ok: boolean; detail: string }
  | { type: 'message'; text: string }
  | { type: 'confirm'; step: number; action: string; label: string; resolve: (yes: boolean) => void }
  | { type: 'done'; status: TaskRecord['status']; summary: string; steps: number };

export type AgentInput = {
  instruction: string;
  geminiApiKey: string;
  settings: Settings;
  profile: UserProfile;
  onEvent: (event: AgentEvent) => void;
  signal?: AbortSignal;
};

export type AgentResult = {
  status: TaskRecord['status'];
  summary: string;
  steps: number;
};

type ToolSpec = {
  name: string;
  args: string;
  description: string;
  /** True when the action changes something outside AdaptiveAI itself. */
  mutatesOtherApp?: boolean;
};

const TOOLS: ToolSpec[] = [
  { name: 'fill', args: '{ "id": <node id>, "value": "<text>" }', description: 'Type text into the editable field with that id.', mutatesOtherApp: true },
  { name: 'click', args: '{ "id": <node id> }', description: 'Tap the element with that id.', mutatesOtherApp: true },
  { name: 'find', args: '{ "query": "<visible text>" }', description: 'Search the current screen for elements whose text matches. Returns fresh ids.' },
  { name: 'tap', args: '{ "x": <int>, "y": <int> }', description: 'Tap raw screen coordinates. Use only when no node id fits.', mutatesOtherApp: true },
  { name: 'long_press', args: '{ "x": <int>, "y": <int> }', description: 'Long-press raw screen coordinates, e.g. to open a context menu.', mutatesOtherApp: true },
  { name: 'swipe', args: '{ "x1": <int>, "y1": <int>, "x2": <int>, "y2": <int> }', description: 'Swipe between coordinates, e.g. to scroll a list with no scrollable node.', mutatesOtherApp: true },
  { name: 'scroll', args: '{ "id": <node id>, "direction": "down"|"up" }', description: 'Scroll the container with that id.' },
  { name: 'launch_app', args: '{ "app": "<app name or Android package>" }', description: 'Open an installed app by its visible name (for example RedBus, Zepto or Blinkit) or package.', mutatesOtherApp: true },
  { name: 'open_url', args: '{ "url": "<https url>" }', description: 'Open a web page in the browser.', mutatesOtherApp: true },
  { name: 'back', args: '{}', description: 'Press the Android back button.', mutatesOtherApp: true },
  { name: 'home', args: '{}', description: 'Go to the home screen.', mutatesOtherApp: true },
  { name: 'screenshot', args: '{}', description: 'Look at an actual screenshot instead of the node tree. Use when the tree is empty or misleading.' },
  { name: 'speak', args: '{ "text": "<what to say>" }', description: 'Say something out loud to the user.' },
  { name: 'ask_user', args: '{ "question": "<question>" }', description: 'Stop and ask the user for missing information or a decision.' },
  { name: 'done', args: '{ "summary": "<what was accomplished>" }', description: 'The task is complete.' },
  { name: 'fail', args: '{ "reason": "<why this cannot be done>" }', description: 'The task cannot be completed.' },
];

export const MUTATING = new Set(TOOLS.filter((t) => t.mutatesOtherApp).map((t) => t.name));

// Actions that are genuinely irreversible, costly, or socially binding — the ONLY ones a
// delegated task should stop and confirm before running. Everything else in MUTATING is
// ordinary navigation (open an app, tap, scroll, swipe, back, home, fill a form field) that
// the user already authorised by delegating the task: "open Flipkart and open the cart" is
// a single command, not a request to approve six separate taps.
//
// This is what makes cross-app tasks actually complete. With `confirmBeforeActing` asking
// about every click, a blind user gets a modal per micro-action ("Tap element 456?") they
// cannot visually verify, so the task stalls right after the app opens — exactly the
// "it opened Flipkart and did nothing" failure.
const HIGH_STAKES_ACTIONS = new Set([
  'pay', 'pay_now', 'purchase', 'buy', 'buy_now', 'place_order', 'placeorder',
  'submit', 'submit_order', 'checkout', 'confirm_purchase', 'send', 'send_message',
  'send_sms', 'send_email', 'message', 'book', 'confirm_booking', 'order',
  'confirm_order', 'delete', 'remove', 'cancel_subscription', 'unsubscribe',
  'signup', 'register', 'login', 'sign_in', 'create_account', 'settle', 'transfer',
]);
// fill is not in HIGH_STAKES_ACTIONS: typing into a form field is ordinary delegation, and
// the system prompt's rule 5 already stops the model from ever filling a password field
// unless the user supplied the value in this conversation. Confirming every fill would
// break the "open Flipkart, open the cart" flow the same way per-click confirms do.
// A delegated task that reaches a real payment/order step will emit a HIGH_STAKES action
// (pay/buy/submit/place_order/send/...) and that is what stops for confirmation.
const confirmNeeded = (action: string): boolean => HIGH_STAKES_ACTIONS.has(action);

function describeTools(settings: Settings): string {
  // "Use vision screenshots" off means the screenshot tool does not exist this run.
  const tools = settings.useVisionWhenAvailable
    ? TOOLS
    : TOOLS.filter((t) => t.name !== 'screenshot');
  return tools.map((t) => `- ${t.name} ${t.args} — ${t.description}`).join('\n');
}

export function buildSystemPrompt(profile: UserProfile, settings: Settings, extra: string): string {
  const verbosity =
    profile.verbosity === 'terse'
      ? 'Be extremely brief. One short sentence per reply.'
      : profile.verbosity === 'detailed'
        ? 'Explain what you are doing and why at each step.'
        : 'Be concise but complete.';

  const complexity =
    profile.languageComplexity === 'simple'
      ? 'Use simple everyday words. Avoid technical jargon entirely.'
      : profile.languageComplexity === 'technical'
        ? 'Technical precision is welcome.'
        : 'Use natural everyday language.';

  const needLines: string[] = [];
  switch (profile.accessibilityNeed) {
    case 'blind':
      needLines.push(
        'The user cannot see the screen. You are their eyes: always call "speak" to report what you found and what you did, and never rely on the user visually confirming anything.',
      );
      needLines.push('Prefer describing elements by their text label rather than by position.');
      break;
    case 'low_vision':
      needLines.push('The user has low vision. Speak your findings aloud as well as writing them.');
      break;
    case 'cognitive':
      needLines.push(
        'The user benefits from clear step-by-step structure. Do one thing at a time and confirm progress in plain language.',
      );
      break;
    case 'motor':
      needLines.push(
        'The user cannot reliably touch the screen. Never ask them to tap something themselves — do it for them with the tools.',
      );
      break;
    case 'deaf_hard_of_hearing':
      needLines.push('The user may not hear spoken output. Always write results as text too.');
      break;
    default:
      break;
  }

  const fieldEntries = Object.entries(profile.savedFields)
    .filter(([, v]) => typeof v === 'string' && v.trim().length > 0)
    .map(([k, v]) => `  ${k}: ${v}`);

  const corrections = (Array.isArray(profile.corrections) ? profile.corrections : [])
    .filter((c) => Boolean(c) && typeof c?.instruction === 'string')
    .slice(0, 6)
    .map((c) => `- "${c.instruction}" → ${typeof c.note === 'string' ? c.note : ''}`);

  return [
    "You are AdaptiveAI, an assistant running ON the user's Android phone. You can see and operate any app on the device through the Android accessibility layer.",
    'There is no server between you and the user. The phone calls Google Gemini Flash directly (free tier).',
    '',
    '## How you see',
    'Each turn you receive a list of the interactive and textual elements currently on screen. Every element has:',
    '  id (use this to act), cls (widget type), t=text, d=content description, r=android resource id,',
    '  [flags] from click/edit/scroll/check/checked/sel/off/pw, and @cx,cy centre coordinates.',
    'Element ids are only valid until the next screen read. Any action changes the screen, so ids must be re-read.',
    '',
    '## Tools',
    describeTools(settings),
    '',
    '## Response format',
    'Reply with EXACTLY ONE JSON object and nothing else. No prose, no markdown fences.',
    '{ "thought": "<one short line of reasoning>", "action": "<tool name>", "args": { ... } }',
    'To finish: { "thought": "...", "action": "done", "args": { "summary": "..." } }',
    '',
    '## Rules',
    '1. One tool call per reply. Wait for the observation before deciding the next step.',
    '2. Prefer "fill"/"click" with a node id over raw "tap" coordinates — ids are accurate, coordinates are guesses.',
    '3. To fill a form: locate the editable field in the tree (or "find" it), "fill" it, then re-read to verify the text actually landed before moving on.',
    '4. Never invent an id. Only use ids present in the most recent screen read.',
    '5. If a field is flagged pw (password), do not fill it unless the user gave you the value in this conversation.',
    settings.useVisionWhenAvailable
      ? '6. If the screen list is empty or tiny, or the app is a game/canvas with no nodes, call "screenshot" to look at the real pixels.'
      : '6. If the screen list is empty or tiny, or the app is a game/canvas with no nodes, the screen cannot be read — tell the user what happened and call "fail".',
    '7. Never complete a purchase, submit a payment, or send a message to a real person without calling "ask_user" first.',
    '8. If you are blocked or unsure, call "ask_user" — do not guess and do not loop.',
    '9. For any shopping, booking, video, or browser app (RedBus, Zepto, Blinkit, Flipkart, Amazon, YouTube, Chrome, BookMyShow and similar): launch it by name, search, fill the form with the user\'s saved details, verify the selected item/date/time/quantity/address/total aloud, then call "ask_user" immediately before payment, login, or sending anything to a real person.',
    '10. Never enter an OTP, CVV, UPI PIN, password, or other secret unless the user explicitly provides it for this task. Never solve or bypass CAPTCHA; call "ask_user" and explain that manual completion is required. If a login wall or anti-bot check blocks you, stop and hand it to the user instead of guessing.',
    `11. Stop after at most ${settings.maxSteps} steps; if not finished, call "fail" with the reason.`,
    '',
    '## This user',
    profile.displayName ? `Name: ${profile.displayName}` : 'Name: not provided',
    verbosity,
    complexity,
    ...needLines,
    fieldEntries.length
      ? `\n## Saved details (use these to fill forms, do not ask again)\n${fieldEntries.join('\n')}`
      : '\n## Saved details\n  none saved yet — ask the user for anything you need',
    corrections.length
      ? `\n## Corrections this user has given you before (obey them)\n${corrections.join('\n')}`
      : '',
    extra ? `\n## Extra context\n${extra}` : '',
  ].join('\n');
}

export function compressTree(tree: ScreenTree, maxNodes: number): string {
  const allNodes = Array.isArray(tree?.nodes) ? tree.nodes : [];
  const nodes = allNodes.slice(0, maxNodes).map((n) => {
    const parts: string[] = [`${n.id}:${n.cls}`];
    if (n.text) parts.push(`t="${truncate(n.text, 60)}"`);
    if (n.desc) parts.push(`d="${truncate(n.desc, 50)}"`);
    if (n.res) parts.push(`r=${n.res.split('/').pop()}`);
    const flags: string[] = [];
    if (n.click) flags.push('click');
    if (n.editable) flags.push('edit');
    if (n.scroll) flags.push('scroll');
    if (n.checkable) flags.push(n.checked ? 'checked' : 'check');
    if (n.selected) flags.push('sel');
    if (n.disabled) flags.push('off');
    if (n.password) flags.push('pw');
    if (flags.length) parts.push(`[${flags.join(',')}]`);
    parts.push(`@${n.cx},${n.cy}`);
    return parts.join(' ');
  });
  const header = `app=${tree?.package ?? 'unknown'} nodes=${tree?.nodeCount ?? allNodes.length}${tree?.truncated ? ' (TRUNCATED)' : ''}`;
  return `${header}\n${nodes.join('\n')}`;
}

function truncate(s: string, n: number): string {
  const clean = s.replace(/\s+/g, ' ').trim();
  return clean.length > n ? `${clean.slice(0, n - 1)}…` : clean;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

type Observation = { ok: boolean; detail: string; settleMs?: number; imageBase64?: string };

export async function runAgent(input: AgentInput): Promise<AgentResult> {
  const { instruction, geminiApiKey, settings, profile, onEvent, signal } = input;

  const fail = (status: TaskRecord['status'], summary: string, steps: number): AgentResult => {
    onEvent({ type: 'message', text: summary });
    onEvent({ type: 'done', status, summary, steps });
    return { status, summary, steps };
  };

  if (!geminiApiKey) {
    return fail(
      'failed',
      'No Gemini API key. Open Settings and paste your free key from aistudio.google.com.',
      0,
    );
  }

  let status;
  try {
    status = await assist.getStatus();
    if (!status || typeof status.accessibilityEnabled !== 'boolean') {
      status = { accessibilityEnabled: false } as any;
    }
  } catch (err) {
    return fail(
      'failed',
      'Could not check accessibility status. ' +
        'Open Settings → Accessibility, confirm AdaptiveAI is on, then try again.',
      0,
    );
  }
  if (!status.accessibilityEnabled) {
    return fail(
      'failed',
      'Accessibility permission is off, so AdaptiveAI cannot see or operate other apps. ' +
        'Open Settings → Accessibility and turn it on.',
      0,
    );
  }

  const messages: GeminiMessage[] = [
    { role: 'system', content: buildSystemPrompt(profile, settings, '') },
    { role: 'user', content: `Task from the user (spoken or typed): "${instruction}"` },
  ];

  let step = 0;
  let pendingImage: string | null = null;

  while (step < settings.maxSteps) {
    if (signal?.aborted) return fail('cancelled', 'Stopped by the user.', step);

    step += 1;
    onEvent({ type: 'thinking', step });

    if (pendingImage) {
      onEvent({ type: 'status', text: 'Looking at screenshot…' });
    } else {
      onEvent({ type: 'status', text: 'Reading screen…' });
      // The accessibility service can be briefly unbound (Android re-binds it, and any UI
      // automation touching the screen makes the framework drop it). Retry before giving up
      // rather than telling the model the screen is empty.
      let tree: ScreenTree | null = null;
      let screenReadError = '';
      for (let attempt = 0; attempt < 3; attempt++) {
        if (signal?.aborted) break;
        try {
          tree = await assist.readScreen(400);
          break;
        } catch (err) {
          screenReadError = err instanceof Error ? err.message : String(err);
          if (attempt === 2 || signal?.aborted) {
            break;
          }
          await sleep(800, signal);
        }
      }
      if (!tree) {
        return fail(
          signal?.aborted ? 'cancelled' : 'failed',
          signal?.aborted
            ? 'Stopped by the user.'
            : `I could not read the current screen after three attempts. ${screenReadError}`,
          step,
        );
      }
      if (tree) {
        messages.push({ role: 'user', content: `Current screen:\n${compressTree(tree, 220)}` });
      }
    }

    let raw: string;
    try {
      const result = await engineChat({
        geminiApiKey,
        settings,
        messages,
        // "Use vision screenshots" off means the model never sees pixels.
        imageBase64: settings.useVisionWhenAvailable ? pendingImage : null,
        signal,
      });
      raw = String(result?.text ?? '');
      onEvent({ type: 'status', text: `answered by ${result.engine} in ${result.ms} ms` });
      console.log(`[agent] answered by ${result.engine} in ${result.ms} ms`);
    } catch (err) {
      if (signal?.aborted) return fail('cancelled', 'Stopped by the user.', step);
      return fail('failed', err instanceof Error ? err.message : String(err), step);
    }
    // The image is consumed only once the reply is valid JSON. Clearing it right after
    // the call threw the captured frame away whenever the model answered in prose, so the
    // retry had to pay for a whole second screenshot of the same pixels.
    const parsed = extractJson(raw);
    if (!parsed || typeof parsed.action !== 'string') {
      messages.push({ role: 'assistant', content: raw });
      messages.push({
        role: 'user',
        content:
          'That was not valid JSON. Reply with exactly one JSON object: ' +
          '{ "thought": "...", "action": "<tool>", "args": { ... } }',
      });
      onEvent({
        type: 'observation',
        step,
        ok: false,
        detail: 'Model reply was not valid JSON; asking again.',
      });
      continue;
    }

    messages.push({ role: 'assistant', content: JSON.stringify(parsed) });
    pendingImage = null;

    const action = String(parsed.action).toLowerCase();
    const args: Record<string, any> =
      parsed.args && typeof parsed.args === 'object' ? parsed.args : {};
    const thought = typeof parsed.thought === 'string' ? parsed.thought : '';

    onEvent({ type: 'action', step, action, args, label: thought || describeAction(action, args) });
    // Emitted for device verification: uiautomator cannot be used during a run because taking
    // over the accessibility framework unbinds the very service the agent depends on.
    // Never log fill's value — rule 5 lets the model put the user's passwords there, and this
    // line persists into Android logcat in release builds.
    const loggableArgs = action === 'fill' ? { id: args.id, value: '<redacted>' } : args;
    console.log(`[agent] step ${step} action=${action} ${JSON.stringify(loggableArgs)}`);

    if (action === 'done') {
      const summary = String(args.summary ?? 'Task completed.');
      if (settings.speakResponses) void speakSafely(summary, settings);
      return succeed(onEvent, summary, step);
    }

    if (action === 'fail') {
      return fail('failed', String(args.reason ?? 'Could not complete the task.'), step);
    }

    if (action === 'ask_user') {
      const question = String(args.question ?? 'I need more information.');
      if (settings.speakResponses) void speakSafely(question, settings);
      // Paused for a human decision, not failed: the summary is the question itself.
      onEvent({ type: 'message', text: question });
      onEvent({ type: 'done', status: 'awaiting_input', summary: question, steps: step });
      return { status: 'awaiting_input', summary: question, steps: step };
    }

    // Only genuinely irreversible actions (pay, send, submit, place an order, delete, login)
    // stop for confirmation. Ordinary delegated navigation — opening an app, tapping, scrolling,
    // filling a form — proceeds so a task like "open Flipkart and open the cart" actually completes
    // instead of stalling on a meaningless per-click modal the user cannot visually verify.
    if (settings.confirmBeforeActing && confirmNeeded(action)) {
      // Observe the abort signal while waiting: a consumer that aborts without resolving the
      // pending confirm must not leave runAgent hung forever (sleep() does the same).
      const approved = await new Promise<boolean>((resolve) => {
        let settled = false;
        const settle = (value: boolean) => {
          if (settled) return;
          settled = true;
          signal?.removeEventListener('abort', onAbort);
          resolve(value);
        };
        const onAbort = () => settle(false);
        if (signal) {
          if (signal.aborted) return settle(false);
          signal.addEventListener('abort', onAbort, { once: true });
        }
        onEvent({ type: 'confirm', step, action, label: describeAction(action, args), resolve: settle });
      });
      if (signal?.aborted) return fail('cancelled', 'Stopped by the user.', step);
      if (!approved) return fail('cancelled', 'You stopped the task.', step);
    }

    if (signal?.aborted) return fail('cancelled', 'Stopped by the user.', step);
    const observation = await execute(action, args, settings, signal);
    onEvent({ type: 'observation', step, ok: observation.ok, detail: observation.detail });
    console.log(`[agent] step ${step} result=${observation.ok ? 'ok' : 'fail'} ${observation.detail.slice(0, 160)}`);
    messages.push({ role: 'user', content: `Observation: ${observation.detail}` });
    if (observation.imageBase64) pendingImage = observation.imageBase64;

    // Keep the transcript inside the context window on long tasks. Drop whole step groups
    // from the front — screen context through its resulting observation — so the history is
    // never cut mid-step with an assistant action left dangling without its observation.
    while (messages.length > 40) {
      const obsIdx = messages.findIndex(
        (m, i) => i >= 2 && m.role === 'user' && typeof m.content === 'string' && m.content.startsWith('Observation:'),
      );
      if (obsIdx >= 0) {
        messages.splice(2, obsIdx - 2 + 1);
      } else if (messages.length > 2) {
        // No Observation yet (invalid-JSON loop): drop oldest screen/assistant pair.
        messages.splice(2, 2);
      } else break;
    }

    await sleep(observation.settleMs ?? 400, signal);
  }

  return fail('failed', `Stopped after ${settings.maxSteps} steps without finishing.`, step);
}

function succeed(
  onEvent: (event: AgentEvent) => void,
  summary: string,
  step: number,
): AgentResult {
  onEvent({ type: 'message', text: summary });
  onEvent({ type: 'done', status: 'completed', summary, steps: step });
  return { status: 'completed', summary, steps: step };
}

export function describeAction(action: string, args: Record<string, any>): string {
  switch (action) {
    case 'fill':
      return `Type "${args.value ?? ''}" into field ${args.id ?? '?'}`;
    case 'click':
      return `Tap element ${args.id ?? '?'}`;
    case 'find':
      return `Look for "${args.query ?? ''}"`;
    case 'tap':
      return `Tap at ${args.x},${args.y}`;
    case 'long_press':
      return `Long-press at ${args.x},${args.y}`;
    case 'swipe':
      return `Swipe ${args.x1},${args.y1} → ${args.x2},${args.y2}`;
    case 'scroll':
      return `Scroll ${args.direction ?? 'down'} on ${args.id ?? '?'}`;
    case 'launch_app':
      return `Open app ${args.app ?? args.package ?? '?'}`;
    case 'open_url':
      return `Open ${args.url ?? '?'}`;
    case 'speak':
      return `Say "${truncate(String(args.text ?? ''), 60)}"`;
    case 'screenshot':
      return 'Take a screenshot';
    case 'back':
      return 'Press back';
    case 'home':
      return 'Go home';
    default:
      return action;
  }
}

async function execute(
  action: string,
  args: Record<string, any>,
  settings: Settings,
  signal?: AbortSignal,
): Promise<Observation> {
  try {
    // Stop must win over an in-flight action: runAgent threads the signal through sleep/
    // engineChat/confirm, but execute used to be blind to it, so a run stopped while the
    // MediaProjection consent dialog was up resumed afterwards and drove the screen
    // alongside the next run.
    if (signal?.aborted) return { ok: false, detail: 'Stopped.', settleMs: 0 };
    switch (action) {
      case 'fill': {
        const id = Number(args.id);
        if (!Number.isFinite(id)) return { ok: false, detail: 'fill needs a numeric id' };
        const res = await assist.fillNode(id, String(args.value ?? ''));
        return {
          ok: res.ok,
          detail: res.ok
            ? `Field ${id} now contains "${res.text}" (via ${res.method ?? 'setText'}).`
            : `Typing was rejected on node ${id} (both setText and paste). Focus the real input with "click" or "find", then "fill" again.`,
          settleMs: 300,
        };
      }
      case 'click': {
        const id = Number(args.id);
        if (!Number.isFinite(id)) return { ok: false, detail: 'click needs a numeric id' };
        const ok = await assist.clickNode(id);
        return {
          ok,
          detail: ok ? `Clicked node ${id}.` : `Click on node ${id} did nothing.`,
          settleMs: 300,
        };
      }
      case 'find': {
        const matches = await assist.findByText(String(args.query ?? ''));
        if (!matches.length) {
          return { ok: false, detail: `Nothing on screen matches "${args.query}".` };
        }
        const lines = matches.slice(0, 20).map((m) => {
          const flags = [m.editable && 'edit', m.click && 'click'].filter(Boolean).join(',');
          return `${m.id}:${m.cls} "${truncate(m.text || m.desc, 50)}"${flags ? ` [${flags}]` : ''} @${m.cx},${m.cy}`;
        });
        return { ok: true, detail: `${matches.length} match(es):\n${lines.join('\n')}`, settleMs: 100 };
      }
      case 'tap': {
        const x = Number(args.x);
        const y = Number(args.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          return { ok: false, detail: 'tap needs numeric x and y coordinates.' };
        }
        const ok = await assist.tap(x, y);
        return { ok, detail: ok ? 'Tapped.' : 'Tap gesture was cancelled by the system.', settleMs: 400 };
      }
      case 'long_press': {
        const x = Number(args.x);
        const y = Number(args.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          return { ok: false, detail: 'long_press needs numeric x and y coordinates.' };
        }
        const ok = await assist.longPress(x, y);
        return { ok, detail: ok ? 'Long-pressed.' : 'Long press was cancelled.', settleMs: 400 };
      }
      case 'swipe': {
        const x1 = Number(args.x1);
        const y1 = Number(args.y1);
        const x2 = Number(args.x2);
        const y2 = Number(args.y2);
        if (!Number.isFinite(x1) || !Number.isFinite(y1) || !Number.isFinite(x2) || !Number.isFinite(y2)) {
          return { ok: false, detail: 'swipe needs numeric x1, y1, x2 and y2 coordinates.' };
        }
        const ok = await assist.swipe(x1, y1, x2, y2);
        return { ok, detail: ok ? 'Swiped.' : 'Swipe gesture was cancelled.', settleMs: 500 };
      }
      case 'scroll': {
        const id = Number(args.id);
        if (!Number.isFinite(id)) return { ok: false, detail: 'scroll needs a numeric id' };
        const ok = await assist.scrollNode(id, String(args.direction ?? 'down') !== 'up');
        return { ok, detail: ok ? 'Scrolled.' : 'That node is not scrollable.', settleMs: 400 };
      }
      case 'launch_app': {
        const requested = String(args.app ?? args.package ?? '').trim();
        if (!requested) return { ok: false, detail: 'launch_app needs an app name.' };
        const apps = await assist.listApps();
        const query = requested.toLocaleLowerCase();
        const match =
          apps.find((app) => app.package.toLocaleLowerCase() === query) ??
          apps.find((app) => app.label.toLocaleLowerCase() === query) ??
          // Only label→query. The old `query.includes(label)` clause made any EMPTY label
          // (the Kotlin fallback can produce one) match every query, so "open Blinkit"
          // could silently launch an unrelated system app.
          apps.find((app) => {
            const label = app.label.toLocaleLowerCase();
            return label.length > 0 && label.includes(query);
          });
        if (!match) {
          // Suggestions by shared tokens (the previous same-predicate filter was always empty).
          const tokens = query.split(/\s+/).filter((t) => t.length > 2);
          const hits = apps
            .map((app) => {
              const label = app.label.toLocaleLowerCase();
              const score = tokens.reduce((n, tok) => n + (label.includes(tok) ? 1 : 0), 0);
              return { label: app.label, score };
            })
            .filter((h) => h.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 5);
          const suggestions = hits.map((h) => h.label).join(', ');
          return {
            ok: false,
            detail: suggestions
              ? `No exact app match for "${requested}". Similar apps: ${suggestions}.`
              : `No installed app named "${requested}" was found.`,
          };
        }
        const ok = await assist.launchApp(match.package);
        return {
          ok,
          detail: ok
            ? `Launched ${match.label}.`
            : `Could not launch ${match.label}.`,
          settleMs: 1600,
        };
      }
      case 'open_url': {
        const ok = await assist.openUrl(String(args.url ?? ''));
        return {
          ok,
          detail: ok
            ? `Opened ${args.url}.`
            : `Could not open ${args.url}. Check the address is a valid URL.`,
          settleMs: 1500,
        };
      }
      case 'back': {
        const ok = await assist.globalAction('back');
        return { ok, detail: ok ? 'Went back.' : 'Back action failed.', settleMs: 450 };
      }
      case 'home': {
        const ok = await assist.globalAction('home');
        return { ok, detail: ok ? 'Went home.' : 'Home action failed.', settleMs: 700 };
      }
      case 'screenshot': {
        if (!settings.useVisionWhenAvailable) {
          return { ok: false, detail: 'Screenshots are turned off in Settings (Use vision screenshots).' };
        }
        if (signal?.aborted) return { ok: false, detail: 'Stopped.', settleMs: 0 };
        const st = await assist.getStatus();
        let notifHint = '';
        if (!st?.captureActive) {
          if (!(await ensureNotificationPermission())) {
            notifHint =
              ' (Notifications are blocked, so the capture stop button in the status bar is hidden — allow them in Settings.)';
          }
          // This raises the system consent dialog and only settles when the user answers.
          const granted = await assist.requestScreenCapture();
          if (signal?.aborted) {
            return { ok: false, detail: 'Stopped.', settleMs: 0 };
          }
          if (!granted) {
            return { ok: false, detail: 'Screen capture was not granted. Open the Screen tab, grant capture, and try again.' };
          }
          // requestScreenCapture resolves after consent; re-check before capturing
          // in the same tick — calling captureScreen immediately would return no frame.
          const st2 = await assist.getStatus();
          if (!st2?.captureActive) {
            return { ok: false, detail: 'Screen capture session did not start. Open the Screen tab and try Screenshot there first.' };
          }
        }
        const base64 = await assist.captureScreen(72);
        if (!base64) return { ok: false, detail: 'Screenshot produced no frame.' };
        return {
          ok: true,
          detail: `Screenshot captured. The image is attached to the next turn.${notifHint}`,
          imageBase64: base64,
          settleMs: 150,
        };
      }
      case 'speak': {
        if (!settings.speakResponses) {
          return { ok: false, detail: `Speech is turned off. The message was: "${truncate(String(args.text ?? ''), 120)}"`, settleMs: 100 };
        }
        const spoke = await speakSafely(String(args.text ?? ''), settings);
        // Report honestly so the model knows the user may not have been informed and can
        // fall back to showing the text. (Note: the native side resolves once the utterance
        // is queued, so a TTS engine failure on the device may still be invisible here.)
        return spoke
          ? { ok: true, detail: 'Spoke to the user.', settleMs: 250 }
          : {
              ok: false,
              detail: `Speech failed — the user may not have heard it. The message was: "${truncate(String(args.text ?? ''), 120)}"`,
              settleMs: 250,
            };
      }
      default:
        return { ok: false, detail: `Unknown action "${action}". Use one of the listed tools.` };
    }
  } catch (err) {
    return { ok: false, detail: `${action} failed: ${err instanceof Error ? err.message : String(err)}` };
  }
}

async function speakSafely(text: string, settings: Settings): Promise<boolean> {
  if (!text) return false;
  try {
    await assist.speak(text, settings.speechRate, settings.language);
    return true;
  } catch {
    // Never let speech failure break the loop — but let the caller report it honestly.
    return false;
  }
}

/** Listens once and resolves with the recognised instruction. */
export async function listenOnce(settings: Settings): Promise<string> {
  const granted = await ensureMicPermission();
  if (!granted) throw new Error('Microphone permission was denied.');
  return listenOnceWithRetry(settings, 0);
}

// Codes that mean "this recognizer instance is broken, a fresh one may work" — a single
// transient ERROR_CLIENT (11) must not fail the mic tap, which is exactly what happened
// on Realme/ColorOS whenever the OEM recycled the recognition service. Samsung returns
// the same class of error through the on-device recognizer, so add the siblings it can
// throw instead of failing the tap.
const RETRYABLE = new Set(['client', 'server', 'audio', 'busy', 'recognizer_crash', 'unavailable']);

async function listenOnceWithRetry(settings: Settings, attempt: number): Promise<string> {
  try {
    return await listenOnceAttempt(settings);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const code = (err as { code?: string } | null)?.code;
    const retryable = code ? RETRYABLE.has(code) : RETRYABLE_CODE_RE.test(message);
    if (attempt < 1 && retryable) {
      // Give the OEM a beat to release the previous binding, then try a clean session.
      await new Promise((r) => setTimeout(r, 600));
      return listenOnceWithRetry(settings, attempt + 1);
    }
    throw err instanceof Error ? err : new Error(message);
  }
}

const RETRYABLE_CODE_RE = /client error|code 11|recognizer|not available|busy|server error/i;

function listenOnceAttempt(settings: Settings): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    let settled = false;
    let unsubscribe: () => void = () => {};
    let timer: ReturnType<typeof setTimeout> | null = null;

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      try { unsubscribe(); } catch {}
      if (timer) clearTimeout(timer);
      fn();
    };

    unsubscribe = subscribeVoice({
      onFinal: (text) => finish(() => resolve(text)),
      onError: (code, message) =>
        finish(() => {
          // TTS failures share the onVoiceError channel with STT failures. A "speak"
          // problem must never reject the mic tap — the user was still listening.
          if (code === 'tts' || code === 'tts_init') return;
          const err = new Error(message || 'Voice input failed.');
          // Carry the native code so the retry path can decide instead of pattern-matching text.
          (err as Error & { code?: string }).code = code;
          reject(err);
        }),
    });

    assist
      .startVoice(settings.language, settings.preferOnDeviceStt)
      .then((started) => {
        // false = no recognizer could be created; fail now instead of hanging until the timer.
        if (!started) {
          const err = new Error('No speech recognizer is available on this device.');
          (err as Error & { code?: string }).code = 'unavailable';
          finish(() => reject(err));
        }
      })
      .catch((err) => finish(() => reject(err instanceof Error ? err : new Error(String(err)))));

    // Hard stop so a silent room can't hang the UI forever.
    timer = setTimeout(() => {
      assist.stopVoice().catch(() => {});
      finish(() => reject(new Error('No speech detected.')));
    }, 20000);
  });
}

