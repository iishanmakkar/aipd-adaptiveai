// Gemini Flash client — free-tier friendly, no backend.
// Free quota is real but capped (~15 req/min, shared daily cap). The app degrades honestly
// when quota hits: the user sees the 429 message, not a silent failure.
export const GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';
// Verified 2026-11-20: gemini-2.0-flash was renamed and 404s; gemini-2.5-flash is
// deprecated — Google routes gemini-2.5-flash to gemini-3.5-flash-lite on 2026-12-01.
// The flash-latest aliases stay: they are the stable names for the default generations.
export const DEFAULT_GEMINI_MODEL = 'gemini-flash-latest';
export const GEMINI_MODEL_CHOICES = [
  'gemini-3.8-flash', // Sep 2026, general-use, frontier-class
  'gemini-3.6-flash', // Jul 2026, general-use, frontier-class
  'gemini-3.5-flash', // May 2026, general-use, 1M context
  'gemini-3.5-flash-lite', // Jul 2026, stable, cost-efficient 3.5 family, free tier
  'gemini-flash-lite-latest', // stable alias — routes to gemini-3.5-flash-lite
  'gemini-2.5-flash', // deprecated, routes to gemini-3.5-flash-lite after 2026-12-01
  'gemini-flash-latest', // stable alias of gemini-2.5-flash (routes to gemini-3.5-flash-lite)
  'gemini-2.5-flash-lite', // established July 2025, free tier
] as const;

function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const on = () => { clearTimeout(timer); cleanup(); resolve(); };
    const timer = setTimeout(() => { cleanup(); resolve(); }, ms);
    // Remove the listener when the timer wins, or every retry stacks another one on a
    // long-lived signal and the listener list grows for the life of the session.
    const cleanup = () => signal?.removeEventListener('abort', on);
    signal?.addEventListener('abort', on, { once: true });
  });
}

export class GeminiError extends Error {
  readonly status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.name = 'GeminiError';
    this.status = status;
  }
}

export type GeminiMessage = { role: 'system' | 'user' | 'assistant'; content: string };

async function postJson(
  apiKey: string,
  path: string,
  payload: unknown,
  timeoutMs: number,
  signal?: AbortSignal,
  attempt = 0,
): Promise<any> {
  if (!apiKey) throw new GeminiError('No Gemini API key set. Add one in Settings.');
  if (signal?.aborted) throw new GeminiError('Stopped by the user.', 0);
  const sep = path.includes('?') ? '&' : '?';
  const url = `${GEMINI_BASE_URL}${path}${sep}key=${encodeURIComponent(apiKey)}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onOuterAbort = () => controller.abort();
  signal?.addEventListener('abort', onOuterAbort);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await res.text();
    let json: any = null;
    try { json = text ? JSON.parse(text) : null; } catch { json = null; }
    if (!res.ok) {
      if (attempt === 0 && !signal?.aborted && (res.status >= 500 || res.status === 429)) {
        await abortableSleep(res.status === 429 ? 3000 : 1200, signal);
        if (signal?.aborted) throw new GeminiError('Stopped by the user.', 0);
        return postJson(apiKey, path, payload, timeoutMs, signal, attempt + 1);
      }
      throw new GeminiError(describeGeminiError(res.status, json, text), res.status);
    }
    return json;
  } catch (err) {
    if (err instanceof GeminiError) throw err;
    const e = err as { name?: string; message?: string };
    if (e?.name === 'AbortError') {
      throw signal?.aborted
        ? new GeminiError('Stopped by the user.', 0)
        : new GeminiError('Gemini request timed out.', 0);
    }
    if (attempt === 0 && !signal?.aborted) {
      await abortableSleep(1200, signal);
      if (signal?.aborted) throw new GeminiError('Stopped by the user.', 0);
      return postJson(apiKey, path, payload, timeoutMs, signal, attempt + 1);
    }
    throw new GeminiError(
      `Could not reach Google Gemini (${e?.message ?? 'network error'}). This device needs internet access — the model runs at Google, not on a server of ours.`,
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onOuterAbort);
  }
}

function describeGeminiError(status: number, json: any, raw: string): string {
  const msg = json?.error?.message ?? raw?.slice(0, 300) ?? '';
  switch (status) {
    case 400:
      return `Gemini rejected the request (400). ${msg}`;
    case 401:
    case 403:
      return `Gemini rejected the API key (${status}). Check the key in Settings — get a free key at aistudio.google.com. ${msg}`;
    case 404:
      return `Model not found on Gemini (${status}). ${msg}`;
    case 429:
      return (
        'Gemini free quota reached (429). Wait a minute and try again. ' +
        "If you are using the app's built-in key, that quota is shared with every other user of it — " +
        'add your own free key from aistudio.google.com in Settings for a quota only you use.'
      );
    default:
      return `Gemini request failed (${status}). ${msg}`;
  }
}

export async function chat(
  apiKey: string,
  model: string,
  messages: GeminiMessage[],
  opts: { temperature?: number; maxTokens?: number; timeoutMs?: number; signal?: AbortSignal; imageBase64?: string } = {},
): Promise<string> {
  const { temperature = 0.2, maxTokens = 1024, timeoutMs = 120000, signal, imageBase64 } = opts;
  const systemTexts = messages.filter((m) => m.role === 'system').map((m) => m.content);
  const turns = messages.filter((m) => m.role !== 'system');
  const contents = turns.map((m, idx) => {
    const isLast = idx === turns.length - 1;
    if (imageBase64 && isLast) {
      return {
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: [
          { text: m.content },
          { inline_data: { mime_type: 'image/jpeg', data: imageBase64 } },
        ],
      };
    }
    return { role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] };
  });
  const payload: any = {
    contents,
    generationConfig: {
      temperature: Math.min(1, Math.max(0, temperature)),
      maxOutputTokens: maxTokens,
      topP: 0.9,
    },
  };
  if (systemTexts.length) {
    payload.systemInstruction = { parts: systemTexts.map((t) => ({ text: t })) };
  }
  const json = await postJson(apiKey, `/models/${model}:generateContent`, payload, timeoutMs, signal);
  // Gemini 2.5+ bills hidden thinking against maxOutputTokens, so a tight budget returns
  // finishReason MAX_TOKENS with a fragment that reads like a normal answer. Callers
  // cannot tell, so fail loudly instead of returning a half-sentence as success.
  const finishReason = json?.candidates?.[0]?.finishReason;
  if (finishReason === 'MAX_TOKENS') {
    throw new GeminiError(
      'Gemini ran out of response tokens before finishing — the answer was cut off. Try again.',
      200,
    );
  }
  const content = extractText(json);
  if (!content) {
    const block = json?.promptFeedback?.blockReason;
    if (block) throw new GeminiError(`Gemini blocked the request (${block}).`, 200);
    throw new GeminiError('Gemini returned no text.', 200);
  }
  return content;
}

function extractText(json: any): string {
  const parts = json?.candidates?.[0]?.content?.parts;
  if (Array.isArray(parts)) {
    return parts.map((p: any) => (typeof p?.text === 'string' ? p.text : '')).join('').trim();
  }
  return '';
}

export function extractJson(raw: string): Record<string, any> | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const trimmed = raw.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidates: string[] = [];
  if (fenced?.[1]) candidates.push(fenced[1].trim());
  candidates.push(trimmed);
  for (const candidate of candidates) {
    const parsed = tryParse(candidate);
    if (parsed) return parsed;
    const sliced = sliceBalanced(candidate);
    if (sliced) {
      const parsedSlice = tryParse(sliced);
      if (parsedSlice) return parsedSlice;
    }
  }
  return null;
}

function tryParse(text: string): Record<string, any> | null {
  try {
    const value = JSON.parse(text);
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch { return null; }
}

function sliceBalanced(text: string): string | null {
  const start = text.indexOf('{');
  if (start === -1) return null;
  let depth = 0; let inString = false; let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) return text.slice(start, i + 1); }
  }
  return null;
}

export async function testApiKey(apiKey: string, timeoutMs = 30000): Promise<{ ok: boolean; modelCount: number; error: string; models: string[] }> {
  if (!apiKey) return { ok: false, modelCount: 0, error: 'Key is empty.', models: [] };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${GEMINI_BASE_URL}/models?key=${encodeURIComponent(apiKey)}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    const text = await res.text();
    let json: any = null;
    try { json = text ? JSON.parse(text) : null; } catch { json = null; }
    if (!res.ok) {
      return { ok: false, modelCount: 0, error: describeGeminiError(res.status, json, text), models: [] };
    }
    const models: string[] = Array.isArray(json?.models)
      ? json.models.map((m: any) => String(m?.name ?? '').replace('models/', '')).filter(Boolean)
      : [];
    return { ok: true, modelCount: models.length, error: '', models };
  } catch (err) {
    const e = err as { name?: string; message?: string };
    return {
      ok: false, modelCount: 0,
      error: e?.name === 'AbortError' ? 'Timed out reaching generativelanguage.googleapis.com.' : `Network error: ${e?.message ?? 'unknown'}`,
      models: [],
    };
  } finally { clearTimeout(timer); }
}
