import { chat, DEFAULT_GEMINI_MODEL, GEMINI_MODEL_CHOICES } from './gemini';
import type { GeminiMessage } from './gemini';
import type { Settings } from './profile';

export type EngineResult = {
  text: string;
  engine: 'gemini';
  ms: number;
};

/** Gemini Flash only. Screen reading, gestures, STT/TTS are on-device free APIs;
 *  reasoning/vision goes to Google (free tier). No NIM, no local llama.cpp. */
export async function engineChat(opts: {
  geminiApiKey: string;
  settings: Settings;
  messages: GeminiMessage[];
  imageBase64?: string | null;
  signal?: AbortSignal;
  maxTokensOverride?: number;
  /** Latency ceiling for this call. Without it every call inherits chat()'s 120 s default,
   *  so a stalled answer step left the user hearing nothing for two minutes. */
  timeoutMs?: number;
}): Promise<EngineResult> {
  const { geminiApiKey, settings, messages, imageBase64, signal, maxTokensOverride, timeoutMs } = opts;
  if (!geminiApiKey) {
    throw new Error('No Gemini API key. Open Settings and paste your free key from aistudio.google.com.');
  }
  const started = Date.now();
  const model = (GEMINI_MODEL_CHOICES as readonly string[]).includes(settings.model) ? settings.model : DEFAULT_GEMINI_MODEL;
  const text = await chat(geminiApiKey, model, messages, {
    temperature: settings.temperature,
    maxTokens: maxTokensOverride ?? 4096,
    timeoutMs,
    signal,
    imageBase64: imageBase64 ?? undefined,
  });
  return { text, engine: 'gemini', ms: Date.now() - started };
}
