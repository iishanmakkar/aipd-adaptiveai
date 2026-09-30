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
  utterance.rate = next.rate;
  utterance.pitch = next.pitch;
  utterance.volume = next.volume;
  if (next.voice) utterance.voice = next.voice;
  const done = () => {
    if (current === utterance) current = null;
    pumping = false;
    notify();
    next.resolve();
    pump();
  };
  utterance.onend = done;
  utterance.onerror = done;
  notify();
  speechSynthesis.speak(utterance);
}

export function enqueueSpeech(text: string, opts?: { rate?: number; pitch?: number; volume?: number; voice?: SpeechSynthesisVoice | null }): Promise<void> {
  if (!('speechSynthesis' in window)) return Promise.resolve();
  return new Promise((resolve) => {
    queue.push({
      text,
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
  queue = [];
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  // The cancelled utterance's onend/onerror fires async and re-pumps an
  // empty queue harmlessly; clear synchronously so state is exact now.
  current = null;
  pumping = false;
  notify();
}
