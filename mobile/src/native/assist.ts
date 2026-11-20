import {
  NativeEventEmitter,
  NativeModules,
  PermissionsAndroid,
  Platform,
} from 'react-native';

type Subscription = ReturnType<NativeEventEmitter['addListener']>;

const Native = NativeModules.AdaptiveAssist;

export const assistAvailable = Boolean(Native);

export type ScreenNode = {
  id: number;
  d: number;
  cls: string;
  text?: string;
  desc?: string;
  res?: string;
  b: [number, number, number, number];
  cx: number;
  cy: number;
  click?: boolean;
  longClick?: boolean;
  editable?: boolean;
  scroll?: boolean;
  checkable?: boolean;
  checked?: boolean;
  selected?: boolean;
  focused?: boolean;
  disabled?: boolean;
  password?: boolean;
};

export type ScreenTree = {
  package: string;
  nodeCount: number;
  truncated: boolean;
  nodes: ScreenNode[];
};

export type TextMatch = {
  id: number;
  text: string;
  desc: string;
  cls: string;
  res: string | null;
  cx: number;
  cy: number;
  editable: boolean;
  click: boolean;
};

export type AssistStatus = {
  accessibilityEnabled: boolean;
  sttAvailable: boolean;
  /** Capability hint: the OS is new enough to offer an offline recognizer. */
  onDeviceStt: boolean;
  /** Whether the most recent listen actually used the offline recognizer. */
  lastListenOnDevice: boolean;
  listening: boolean;
  captureActive: boolean;
  /** True while the microphone foreground service keeps an assist session alive. */
  assistSession?: boolean;
  foregroundApp: string;
  sdkInt: number;
};

export type InstalledApp = { package: string; label: string };

export type VoiceEvent = { text?: string; code?: string; message?: string; utteranceId?: string };

function requireNative(): void {
  if (!Native) {
    throw new Error(
      'The AdaptiveAssist native module is missing. This build does not include the ' +
        'accessibility/automation layer — rebuild the APK with assembleRelease.',
    );
  }
}

function parseJson(raw: string, what: string): any {
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`The native layer returned malformed ${what}. Try again.`);
  }
}

export const assist = {
  async getStatus(): Promise<AssistStatus> {
    if (!Native) {
      return {
        accessibilityEnabled: false,
        sttAvailable: false,
        onDeviceStt: false,
        lastListenOnDevice: false,
        listening: false,
        captureActive: false,
        assistSession: false,
        foregroundApp: '',
        sdkInt: Platform.OS === 'android' ? (Platform.Version as number) : 0,
      };
    }
    try {
      const res = await Native.getStatus();
      if (!res || typeof res !== 'object') {
        return {
          accessibilityEnabled: false,
          sttAvailable: false,
          onDeviceStt: false,
          lastListenOnDevice: false,
          listening: false,
          captureActive: false,
          assistSession: false,
          foregroundApp: '',
          sdkInt: Platform.OS === 'android' ? (Platform.Version as number) : 0,
        };
      }
      return res as AssistStatus;
    } catch {
      return {
        accessibilityEnabled: false,
        sttAvailable: false,
        onDeviceStt: false,
        lastListenOnDevice: false,
        listening: false,
        captureActive: false,
        assistSession: false,
        foregroundApp: '',
        sdkInt: Platform.OS === 'android' ? (Platform.Version as number) : 0,
      };
    }
  },

  async openAccessibilitySettings(): Promise<boolean> {
    requireNative();
    return Native.openAccessibilitySettings();
  },

  async openAppSettings(): Promise<boolean> {
    requireNative();
    return Native.openAppSettings();
  },

  async readScreen(limit = 500): Promise<ScreenTree> {
    requireNative();
    const raw: string = await Native.readScreen(limit);
    const tree = parseJson(raw, 'screen data') as ScreenTree;
    if (!tree || typeof tree !== 'object' || !Array.isArray(tree.nodes)) {
      throw new Error('The native layer returned an empty screen. Try again.');
    }
    return tree;
  },

  async findByText(query: string): Promise<TextMatch[]> {
    requireNative();
    const raw: string = await Native.findByText(query);
    const parsed = parseJson(raw, 'search results');
    if (!Array.isArray(parsed)) throw new Error('The native layer returned malformed search results.');
    return parsed as TextMatch[];
  },

  async fillNode(id: number, value: string): Promise<{ ok: boolean; text: string; method?: string }> {
    requireNative();
    const raw: string = await Native.fillNode(id, value);
    const res = parseJson(raw, 'fill result');
    if (!res || typeof res !== 'object') return { ok: false, text: '' };
    return {
      ok: Boolean(res.ok),
      text: String(res.text ?? ''),
      method: typeof res.method === 'string' ? res.method : undefined,
    };
  },

  async clickNode(id: number): Promise<boolean> {
    requireNative();
    return Native.clickNode(id);
  },

  async scrollNode(id: number, forward: boolean): Promise<boolean> {
    requireNative();
    return Native.scrollNode(id, forward);
  },

  async tap(x: number, y: number): Promise<boolean> {
    requireNative();
    return Native.tap(x, y);
  },

  async longPress(x: number, y: number): Promise<boolean> {
    requireNative();
    return Native.longPress(x, y);
  },

  async swipe(x1: number, y1: number, x2: number, y2: number, durationMs = 320): Promise<boolean> {
    requireNative();
    return Native.swipe(x1, y1, x2, y2, durationMs);
  },

  async globalAction(action: 'back' | 'home' | 'recents' | 'notifications'): Promise<boolean> {
    requireNative();
    return Native.globalAction(action);
  },

  async launchApp(packageName: string): Promise<boolean> {
    requireNative();
    return Native.launchApp(packageName);
  },

  async openUrl(url: string): Promise<boolean> {
    requireNative();
    return Native.openUrl(url);
  },

  async listApps(): Promise<InstalledApp[]> {
    if (!Native) return [];
    try {
      const res = await Native.listApps();
      return Array.isArray(res) ? res : [];
    } catch {
      return [];
    }
  },

  async requestScreenCapture(): Promise<boolean> {
    requireNative();
    return Native.requestScreenCapture();
  },

  async captureScreen(quality = 72): Promise<string> {
    requireNative();
    return Native.captureScreen(quality);
  },

  async shareScreen(quality = 90): Promise<boolean> {
    requireNative();
    return Native.shareScreen(quality);
  },

  async stopScreenCapture(): Promise<boolean> {
    requireNative();
    return Native.stopScreenCapture();
  },

  /** On-device OCR (ML Kit) of the captured screen. Free, no API key. Requires capture session. */
  async ocrScreen(quality = 72): Promise<string> {
    requireNative();
    return Native.ocrScreen(quality);
  },

  /** MediaPipe object detection over the captured frame. Returns [{label, score, cx, cy}]. */
  async detectObjects(quality = 72): Promise<{ label: string; score: number; cx: number; cy: number }[]> {
    requireNative();
    const raw: string = await Native.detectObjects(quality);
    const parsed = parseJson(raw, 'detections');
    if (!Array.isArray(parsed)) throw new Error('The native layer returned malformed detections.');
    return parsed;
  },

  /** Starts the microphone foreground service so listening survives backgrounding. */
  async startAssistSession(): Promise<boolean> {
    requireNative();
    return Native.startAssistSession();
  },

  async stopAssistSession(): Promise<boolean> {
    requireNative();
    return Native.stopAssistSession();
  },

  async startVoice(language = 'en-US', preferOnDevice = true): Promise<boolean> {
    requireNative();
    return Native.startVoice(language, preferOnDevice);
  },

  async stopVoice(): Promise<boolean> {
    requireNative();
    return Native.stopVoice();
  },

  async cancelVoice(): Promise<boolean> {
    requireNative();
    return Native.cancelVoice();
  },

  async speak(text: string, rate = 1.0, language = 'en-US'): Promise<string> {
    requireNative();
    return Native.speak(text, rate, language);
  },

  async stopSpeaking(): Promise<boolean> {
    requireNative();
    return Native.stopSpeaking();
  },
};

let emitter: NativeEventEmitter | null = null;

function getEmitter(): NativeEventEmitter | null {
  if (Platform.OS !== 'android' || !Native) return null;
  if (!emitter) {
    try {
      emitter = new NativeEventEmitter(Native);
    } catch {
      emitter = null;
    }
  }
  return emitter;
}

export type VoiceHandlers = {
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
  onError?: (code: string, message: string) => void;
  onSpeakDone?: (utteranceId: string) => void;
};

export function subscribeVoice(handlers: VoiceHandlers): () => void {
  const em = getEmitter();
  if (!em) return () => {};
  const subs: Subscription[] = [];
  if (handlers.onPartial) {
    subs.push(em.addListener('onVoicePartial', (e: VoiceEvent) => handlers.onPartial?.(e.text ?? '')));
  }
  if (handlers.onFinal) {
    subs.push(em.addListener('onVoiceFinal', (e: VoiceEvent) => handlers.onFinal?.(e.text ?? '')));
  }
  if (handlers.onError) {
    subs.push(
      em.addListener('onVoiceError', (e: VoiceEvent) => handlers.onError?.(e.code ?? 'unknown', e.message ?? '')),
    );
  }
  if (handlers.onSpeakDone) {
    subs.push(
      em.addListener('onSpeakDone', (e: VoiceEvent) => handlers.onSpeakDone?.(e.utteranceId ?? '')),
    );
  }
  return () => subs.forEach((s) => s.remove());
}

export async function ensureMicPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return true;
  try {
    const granted = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO);
    if (granted) return true;
    const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO, {
      title: 'Microphone access',
      message: 'AdaptiveAI needs the microphone so you can give tasks by voice.',
      buttonPositive: 'Allow',
      buttonNegative: 'Deny',
    });
    return result === PermissionsAndroid.RESULTS.GRANTED;
  } catch {
    return false;
  }
}

export async function ensureNotificationPermission(): Promise<boolean> {
  if (Platform.OS !== 'android' || Platform.Version < 33) return true;
  try {
    const perm = 'android.permission.POST_NOTIFICATIONS' as any;
    const granted = await PermissionsAndroid.check(perm);
    if (granted) return true;
    const result = await PermissionsAndroid.request(perm, {
      title: 'Notifications',
      message: 'Android requires a notification while AdaptiveAI is listening or capturing the screen.',
      buttonPositive: 'Allow',
      buttonNegative: 'Deny',
    });
    return result === PermissionsAndroid.RESULTS.GRANTED;
  } catch {
    return false;
  }
}

export type AssistLoopHandlers = {
  /** A complete utterance was heard — run it (agent, SOS, anything). */
  onFinal: (text: string) => void;
  /** Live partial transcript for the UI. */
  onPartial?: (text: string) => void;
  /** Recognition could not run or keeps failing — the loop has given up. */
  onFatal?: (message: string) => void;
  /** Fired after every loop turn (final, error, or re-arm) so the UI can show liveness. */
  onIdle?: () => void;
};

/**
 * Continuous listening loop for background assist sessions. The platform SpeechRecognizer is
 * one-shot, so "always listening" means re-arming it after every final or recoverable error.
 * The loop lives in JS but keeps running while backgrounded because the microphone
 * foreground service keeps the process alive. Guard rails:
 * - transient errors (network/server/client/no_match/…) back off 1s → 10s capped and
 *   keep re-arming forever — the loop only stops on truly fatal codes ("permissions",
 *   "unavailable") or an explicit stop();
 * - if the foreground service was killed while backgrounded, the loop restarts it
 *   before the next arm instead of dying;
 * - stop() fully tears the session down (recognizer + foreground service).
 */
let activeLoop: { stop: () => void; active: () => boolean } | null = null;

/**
 * While a manual mic tap is in progress the background loop must not re-arm the
 * singleton recognizer — doing so calls startVoice mid-listen and kills the tap's
 * session (both then receive each other's uncorrelated events on one global bus).
 * The loop keeps its subscription and simply skips arming until the hold is released.
 */
let voiceHold = false;
const holdWaiters: Array<() => void> = [];

export function setVoiceHold(held: boolean): void {
  voiceHold = held;
  if (!held) {
    const waiters = holdWaiters.splice(0, holdWaiters.length);
    for (const w of waiters) {
      try { w(); } catch {}
    }
  }
}

function whenHoldReleased(): Promise<void> {
  if (!voiceHold) return Promise.resolve();
  return new Promise((resolve) => holdWaiters.push(resolve));
}

export function startAssistLoop(
  settings: { language: string; preferOnDeviceStt: boolean },
  handlers: AssistLoopHandlers,
): { stop: () => void; active: () => boolean } {
  // Singleton: a second mount (StrictMode remount, tab switch) must not double-subscribe.
  if (activeLoop?.active()) return activeLoop;
  let stopped = false;
  let consecutiveFailures = 0;
  // Anything the recognizer can recover from on the next arm: end-of-utterance
  // noise, transient network drops, the recognizer being busy, and internal
  // client/server hiccups that a fresh SpeechRecognizer instance clears.
  const RECOVERABLE = new Set([
    'cancelled', 'busy', 'no_match', 'timeout', 'audio',
    'network', 'server', 'client', 'unknown', 'language',
  ]);
  // Only these mean listening can never work in this install; everything else
  // must NOT kill the background session — that was the "Background listening
  // stopped" bug: 5 transient errors (usually ERROR_CLIENT when the recognizer
  // service is recycled while backgrounded) permanently stopped the loop.
  const FATAL = new Set(['permissions', 'unavailable']);

  // Degrade the same way subscribeVoice and getStatus do when the native layer is absent —
  // never throw synchronously out of the re-arm timer.
  if (!assistAvailable) {
    handlers.onFatal?.('The AdaptiveAssist native module is missing in this build.');
    return { stop: () => {}, active: () => false };
  }

  let unsub: (() => void) = () => {};
  try {
    unsub = subscribeVoice({
      onPartial: (text) => {
        if (stopped) return;
        clearWatchdog();
        handlers.onPartial?.(text);
      },
      onFinal: (text) => {
        if (stopped) return;
        clearWatchdog();
        consecutiveFailures = 0;
        if (text.trim()) handlers.onFinal(text.trim());
        handlers.onIdle?.();
        arm(800);
      },
      onError: (code, message) => {
        if (stopped) return;
        clearWatchdog();
        // TTS problems ride the same channel as STT problems; they are not recognition
        // failures and must not consume the backoff budget.
        if (code === 'tts' || code === 'tts_init') return;
        if (FATAL.has(code)) {
          stopAll();
          handlers.onFatal?.(message);
          return;
        }
        if (RECOVERABLE.has(code)) {
          handlers.onIdle?.();
          consecutiveFailures += 1;
          const floor = code === 'busy' || code === 'audio' ? 1500 : 1000;
          arm(Math.min(10000, Math.max(floor, 1000 * consecutiveFailures)));
          return;
        }
        // Unknown hard error: back off, and if the foreground service died while
        // we were backgrounded, restart it instead of giving up.
        consecutiveFailures += 1;
        void ensureSessionAlive();
        handlers.onIdle?.();
        arm(Math.min(10000, 1000 * consecutiveFailures));
      },
    });
  } catch (e) {
    handlers.onFatal?.(e instanceof Error ? e.message : String(e));
    return { stop: () => {}, active: () => false };
  }

  let armTimer: ReturnType<typeof setTimeout> | null = null;
  let watchdog: ReturnType<typeof setTimeout> | null = null;
  // If the recognition service's process is recycled mid-session, AOSP delivers NO
  // callback at all — no onError, no onResults — so nothing would ever call arm() again
  // and background listening would silently die. This watchdog notices the silence.
  const WATCHDOG_MS = 12000;

  function clearWatchdog() {
    if (watchdog) clearTimeout(watchdog);
    watchdog = null;
  }

  function armWatchdog() {
    clearWatchdog();
    if (stopped) return;
    watchdog = setTimeout(() => {
      if (stopped) return;
      // Silence for 12s: treat as a dead recognizer, tear it down and re-arm.
      void assist.stopVoice().catch(() => {});
      consecutiveFailures += 1;
      handlers.onIdle?.();
      arm(Math.min(10000, 1000 * consecutiveFailures));
    }, WATCHDOG_MS);
  }

  /// The microphone FGS is what keeps this process alive in the background; if it
  /// was killed (doze, OEM task killer, system restart), recognition errors are
  /// just symptoms. Restart the session before the next arm instead of dying.
  async function ensureSessionAlive() {
    if (stopped) return;
    try {
      const status = await assist.getStatus();
      // stopAll() (user toggled listening off) may have run while we were awaiting.
      // Restarting the session now would resurrect the microphone FGS after "off".
      if (stopped) return;
      if (status.assistSession === false) await assist.startAssistSession();
    } catch {
      // startAssistSession from a backgrounded process may be refused on
      // Android 14+; the next arm() will surface that if it persists.
    }
  }

  async function arm(delayMs: number) {
    if (stopped) return;
    clearWatchdog();
    if (armTimer) clearTimeout(armTimer);
    armTimer = setTimeout(() => {
      if (stopped) return;
      // A manual mic tap owns the singleton recognizer right now — wait it out instead
      // of stealing it mid-listen.
      void whenHoldReleased().then(() => {
        if (stopped || voiceHold) return;
        // Watchdog on every arm: if the FGS was killed while backgrounded, bring it back
        // before listening again, otherwise recognition just errors in a loop.
        void ensureSessionAlive();
        void assist
          .startVoice(settings.language, settings.preferOnDeviceStt)
          .then((ok) => {
            if (stopped) return;
            if (!ok) {
              // NOTE: a successful start must NOT reset consecutiveFailures — VoiceInput
              // resolves true before the recognizer even binds, so resetting here made the
              // backoff unreachable (1s → 10s was never reached) and the loop re-bound a
              // fresh recognizer every second while the old one was still alive for 2s.
              // The counter is reset on a real terminal event (onFinal) instead.
              consecutiveFailures += 1;
              void ensureSessionAlive();
              arm(Math.min(10000, 1000 * consecutiveFailures));
            } else {
              armWatchdog();
            }
          })
          .catch((err) => {
            if (stopped) return;
            const code = (err as { code?: string } | null)?.code;
            // A revoked mic permission or a missing recognizer never recovers by retrying;
            // looping on it just burns battery and hides the real problem from the user.
            if (code === 'permissions' || code === 'unavailable') {
              stopAll();
              handlers.onFatal?.(err instanceof Error ? err.message : String(err));
              return;
            }
            consecutiveFailures += 1;
            arm(Math.min(10000, 1000 * consecutiveFailures));
          });
      });
    }, delayMs);
  }

  function stopAll() {
    stopped = true;
    if (armTimer) clearTimeout(armTimer);
    armTimer = null;
    clearWatchdog();
    unsub();
    void assist.stopVoice().catch(() => {});
    void assist.stopAssistSession().catch(() => {});
    if (activeLoop === handle) activeLoop = null;
  }

  // Kick off immediately.
  arm(0);

  const handle = {
    stop: stopAll,
    active: () => !stopped,
  };
  activeLoop = handle;
  return handle;
}
