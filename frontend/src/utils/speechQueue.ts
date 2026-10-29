/**
 * Single app-wide FIFO over the one global `speechSynthesis`: every hook
 * instance enqueues here, so chat answers and monitor narrations can no
 * longer cancel each other mid-sentence. `speak()` resolves when its own
 * utterance ends; `cancelSpeech()` clears the queue and stops output.
 */
interface QueuedSpeech {
  text: string;
  rate: number;
  pitch: number;
  volume: number;
  voice: SpeechSynthesisVoice | null;
  resolve: () => void;
}

let queue: QueuedSpeech[] = [];
let pumping = false;
let current: SpeechSynthesisUtterance | null = null;
// The resolve of the in-flight utterance: cancelSpeech() must settle it
// (and every queued item) - dropping them left every `await speak()`
// hanging forever, which in turn wedged the monitor poll loop.
let currentResolve: (() => void) | null = null;
// Watchdog timers for the in-flight utterance (see pump): cancelSpeech must
// clear them too, or the resume interval keeps firing for a dead utterance.
let currentWatchdog: number | null = null;
let currentHardStop: number | null = null;
function clearWatchdogs() {
  if (currentWatchdog !== null) { clearInterval(currentWatchdog); currentWatchdog = null; }
  if (currentHardStop !== null) { clearTimeout(currentHardStop); currentHardStop = null; }
}
const listeners = new Set<() => void>();

function notify() {
  for (const fn of listeners) fn();
}

export function onSpeechQueueChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function speechQueueDepth(): number {
  return queue.length + (current ? 1 : 0);
}

function pump(): void {
  if (pumping) return;
  const next = queue.shift();
  if (!next) {
    notify();
    return;
  }
  pumping = true;
  const utterance = new SpeechSynthesisUtterance(next.text);
  current = utterance;
  currentResolve = next.resolve;
  utterance.rate = next.rate;
  utterance.pitch = next.pitch;
  utterance.volume = next.volume;
  if (next.voice) utterance.voice = next.voice;
  const done = () => {
    // A cancelled utterance's end event still fires async — after cancelSpeech
    // reset the state and a NEW utterance may already be speaking. Letting the
    // stale event run set pumping=false and re-pump overlapped the new speech
    // and desynced the queue permanently.
    if (current !== utterance) return;
    current = null;
    currentResolve = null;
    pumping = false;
    clearWatchdogs();
    notify();
    next.resolve();
    pump();
  };
  // Chromium pause bug (crbug 41222409 et al.): speechSynthesis pauses long
  // utterances (~15s) and onend never fires until resume() is called, so
  // `await speak(answer)` hung forever and submitInFlightRef latched — every
  // later submit returned silently and the session was wedged until reload.
  // The interval pokes resume() (a no-op while actually speaking); the hard
  // stop force-settles even if the engine is truly gone. Cleared in done().
  const estimate = Math.ceil((next.text.length * 80) / Math.max(next.rate, 0.1)) + 30000;
  currentWatchdog = window.setInterval(() => {
    try { speechSynthesis.resume(); } catch { /* engine gone; hard stop settles */ }
  }, 10000);
  currentHardStop = window.setTimeout(() => {
    if (current !== utterance) return;
    try { speechSynthesis.cancel(); } catch { /* nothing playing */ }
    done();
  }, estimate);
  utterance.onend = done;
  utterance.onerror = done;
  notify();
  try {
    speechSynthesis.speak(utterance);
  } catch {
    done();
  }
}

export function stripMarkdownForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' code ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, '$1$2')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^[\s]*[-*•]\s+/gm, '')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function enqueueSpeech(text: string, opts?: { rate?: number; pitch?: number; volume?: number; voice?: SpeechSynthesisVoice | null }): Promise<void> {
  if (!('speechSynthesis' in window)) return Promise.resolve();
  const clean = stripMarkdownForSpeech(text);
  if (!clean) return Promise.resolve();
  return new Promise((resolve) => {
    queue.push({
      text: clean,
      rate: opts?.rate ?? 1,
      pitch: opts?.pitch ?? 1,
      volume: opts?.volume ?? 1,
      voice: opts?.voice ?? null,
      resolve,
    });
    notify();
    pump();
  });
}

export function cancelSpeech(): void {
  // Settle every waiter: an `await speak()` abandoned here would hang its
  // caller forever (the monitor's poll loop wedged exactly this way).
  const pending = queue;
  queue = [];
  for (const item of pending) {
    try { item.resolve(); } catch { /* already settled */ }
  }
  const resolveCurrent = currentResolve;
  currentResolve = null;
  clearWatchdogs();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  // The cancelled utterance's onend/onerror fires async and re-pumps an
  // empty queue harmlessly; clear synchronously so state is exact now.
  current = null;
  pumping = false;
  notify();
  if (resolveCurrent) {
    try { resolveCurrent(); } catch { /* already settled */ }
  }
}
