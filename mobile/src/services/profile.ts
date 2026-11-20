import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Alert } from 'react-native';
import { useSyncExternalStore } from 'react';

import { DEFAULT_GEMINI_MODEL, GEMINI_MODEL_CHOICES } from './gemini';
import { EMBEDDED_GEMINI_KEY } from './embeddedGeminiKey';

const SETTINGS_KEY = 'adaptiveai.settings.v1';
const PROFILE_KEY = 'adaptiveai.profile.v1';
const GEMINI_KEY_SECRET = 'gemini_api_key';
const TASKS_KEY = 'adaptiveai.tasks.v1';

export type AccessibilityNeed =
  | 'none'
  | 'blind'
  | 'low_vision'
  | 'cognitive'
  | 'motor'
  | 'deaf_hard_of_hearing';

export type Settings = {
  /** Gemini Flash model id, e.g. gemini-2.0-flash (free tier). */
  model: string;
  speakResponses: boolean;
  speechRate: number;
  language: string;
  preferOnDeviceStt: boolean;
  confirmBeforeActing: boolean;
  maxSteps: number;
  temperature: number;
  useVisionWhenAvailable: boolean;
  useOrchestrator: boolean;
  backgroundListening: boolean;
};

export type SavedFields = {
  fullName: string;
  email: string;
  phone: string;
  address: string;
  city: string;
  postcode: string;
  country: string;
  dateOfBirth: string;
};

export type Correction = {
  id: string;
  at: number;
  instruction: string;
  note: string;
};

export type FrequentTask = {
  phrase: string;
  count: number;
  lastAt: number;
};

/** A trusted person an emergency message can be sent to. On-device only, never uploaded. */
export type CareContact = {
  id: string;
  name: string;
  phone: string;
};

export type UserProfile = {
  displayName: string;
  accessibilityNeed: AccessibilityNeed;
  verbosity: 'terse' | 'normal' | 'detailed';
  languageComplexity: 'simple' | 'standard' | 'technical';
  uiScale: number;
  highContrast: boolean;
  savedFields: SavedFields;
  corrections: Correction[];
  frequentTasks: FrequentTask[];
  careContacts: CareContact[];
};

export type TaskRecord = {
  id: string;
  at: number;
  instruction: string;
  status: 'completed' | 'failed' | 'cancelled' | 'running' | 'awaiting_input';
  summary: string;
  steps: number;
  app: string;
};

export const DEFAULT_SETTINGS: Settings = {
  model: DEFAULT_GEMINI_MODEL,
  speakResponses: true,
  speechRate: 1.0,
  language: 'en-US',
  preferOnDeviceStt: true,
  confirmBeforeActing: true,
  maxSteps: 12,
  temperature: 0.2,
  useVisionWhenAvailable: false,
  useOrchestrator: true,
  backgroundListening: false,
};

export const DEFAULT_PROFILE: UserProfile = {
  displayName: '',
  accessibilityNeed: 'none',
  verbosity: 'normal',
  languageComplexity: 'standard',
  uiScale: 1,
  highContrast: false,
  savedFields: {
    fullName: '',
    email: '',
    phone: '',
    address: '',
    city: '',
    postcode: '',
    country: '',
    dateOfBirth: '',
  },
  corrections: [],
  frequentTasks: [],
  careContacts: [],
};

type Store = {
  settings: Settings;
  profile: UserProfile;
  tasks: TaskRecord[];
  geminiApiKey: string;
  geminiKeyUncertain: boolean;
  loaded: boolean;
};

let state: Store = {
  settings: DEFAULT_SETTINGS,
  profile: DEFAULT_PROFILE,
  tasks: [],
  geminiApiKey: '',
  geminiKeyUncertain: false,
  loaded: false,
};

const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

function set(patch: Partial<Store>): void {
  state = { ...state, ...patch };
  emit();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getSnapshot(): Store {
  return state;
}

export function useStore(): Store {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function useSettings(): Settings {
  return useStore().settings;
}

export function useProfile(): UserProfile {
  return useStore().profile;
}

export function useTasks(): TaskRecord[] {
  return useStore().tasks;
}

export function useGeminiApiKey(): string {
  // User-saved Keystore key wins; otherwise fall back to the key baked into this APK.
  return useStore().geminiApiKey || EMBEDDED_GEMINI_KEY;
}

export function useHasUserKey(): boolean {
  return Boolean(useStore().geminiApiKey);
}

export function useGeminiKeyUncertain(): boolean {
  return useStore().geminiKeyUncertain;
}

export async function loadAll(): Promise<void> {
  const startSettings = state.settings;
  const startProfile = state.profile;
  const startTasks = state.tasks;
  const startKey = state.geminiApiKey;

  async function safeGet(key: string): Promise<string | null> {
    try { return await AsyncStorage.getItem(key); } catch { return null; }
  }
  const [rawSettings, rawProfile, rawTasks] = await Promise.all([
    safeGet(SETTINGS_KEY),
    safeGet(PROFILE_KEY),
    safeGet(TASKS_KEY),
  ]);

  let geminiApiKey = state.geminiApiKey;
  let geminiKeyUncertain = false;
  try {
    const stored = await withTimeout(SecureStore.getItemAsync(GEMINI_KEY_SECRET).catch(() => undefined), 15000, undefined);
    if (stored !== undefined) {
      geminiApiKey = stored ?? '';
    } else {
      geminiKeyUncertain = true;
    }
  } catch {
    geminiKeyUncertain = true;
  }

  const parsedTasks = safeParse(rawTasks);
  const validTasks = Array.isArray(parsedTasks)
    ? (parsedTasks as any[])
        .filter((t: any): t is TaskRecord => Boolean(t) && typeof t.id === 'string' && typeof t.instruction === 'string')
        .map((t: any) => ({
          id: String(t.id).slice(0, 64),
          at: num(t.at, Date.now(), 0, 9999999999999),
          instruction: String(t.instruction).slice(0, 500),
          status: ['completed', 'failed', 'cancelled', 'running', 'awaiting_input'].includes(t.status) ? t.status : 'failed',
          summary: typeof t.summary === 'string' ? t.summary.slice(0, 1000) : '',
          steps: Math.round(num(t.steps, 0, 0, 10000)),
          app: typeof t.app === 'string' ? t.app.slice(0, 120) : '',
        }))
        .slice(0, 200)
    : [];
  set({
    settings: state.settings !== startSettings ? state.settings : mergeSettings(safeParse(rawSettings)),
    profile: state.profile !== startProfile ? state.profile : mergeProfile(safeParse(rawProfile)),
    tasks: state.tasks !== startTasks ? state.tasks : validTasks,
    geminiApiKey: state.geminiApiKey !== startKey ? state.geminiApiKey : geminiApiKey,
    geminiKeyUncertain: state.geminiApiKey !== startKey ? state.geminiKeyUncertain : geminiKeyUncertain,
    loaded: true,
  });
}

function num(n: unknown, def: number, lo: number, hi: number): number {
  const v = typeof n === 'number' ? n : Number(n);
  if (!Number.isFinite(v)) return def;
  return Math.min(hi, Math.max(lo, v));
}

function mergeSettings(raw: any): Settings {
  const merged = { ...DEFAULT_SETTINGS, ...(raw ?? {}) };
  // Migrate old NIM/local settings: keep only Gemini fields, ignore the rest.
  if (typeof merged.model !== 'string' || !merged.model.trim()) {
    // Old textModel is a NIM id — never reuse it for Gemini.
    merged.model = DEFAULT_SETTINGS.model;
  } else {
    const candidate = merged.model.trim().slice(0, 80);
    // Whitelist: a NIM-era or garbage id would 404 every call — fall back to default.
    merged.model = (GEMINI_MODEL_CHOICES as readonly string[]).includes(candidate) ? candidate : DEFAULT_SETTINGS.model;
  }
  merged.speakResponses = Boolean(merged.speakResponses);
  merged.preferOnDeviceStt = Boolean(merged.preferOnDeviceStt);
  merged.confirmBeforeActing = Boolean(merged.confirmBeforeActing);
  merged.useVisionWhenAvailable = Boolean(merged.useVisionWhenAvailable);
  merged.useOrchestrator = Boolean(merged.useOrchestrator);
  merged.backgroundListening = Boolean(merged.backgroundListening);
  merged.speechRate = num(merged.speechRate, 1.0, 0.5, 2.0);
  // Lower bound 3 matches the Stepper range so a persisted value never jumps on first tap.
  merged.maxSteps = Math.round(num(merged.maxSteps, 12, 3, 30));
  merged.temperature = num(merged.temperature, 0.2, 0, 1);
  if (typeof merged.language !== 'string' || !/^[a-z]{2}-[A-Z]{2}$/.test(merged.language)) merged.language = DEFAULT_SETTINGS.language;
  // Drop any leftover NIM-era fields so they never leak into the Gemini path.
  delete (merged as any).engine;
  delete (merged as any).textModel;
  delete (merged as any).visionModel;
  delete (merged as any).availableModels;
  return merged as Settings;
}

function safeParse(raw: string | null): any {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function withTimeout<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise<T>((resolve) => {
    const timer = setTimeout(() => resolve(fallback), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve(fallback);
      },
    );
  });
}

function mergeProfile(raw: any): UserProfile {
  if (!raw || typeof raw !== 'object') return DEFAULT_PROFILE;
  const saved = (raw.savedFields && typeof raw.savedFields === 'object') ? raw.savedFields : {};
  const strFields: SavedFields = { ...DEFAULT_PROFILE.savedFields };
  (Object.keys(DEFAULT_PROFILE.savedFields) as (keyof SavedFields)[]).forEach((k) => {
    if (typeof saved[k] === 'string') strFields[k] = (saved[k] as string).slice(0, 4000);
  });
  const corrections = Array.isArray(raw.corrections)
    ? raw.corrections.filter((c: any): c is Correction => Boolean(c) && typeof c.instruction === 'string').map((c: any) => ({
        id: typeof c.id === 'string' ? c.id.slice(0, 64) : `c${Date.now()}`,
        at: num(c.at, Date.now(), 0, 9999999999999),
        instruction: String(c.instruction).slice(0, 200),
        note: typeof c.note === 'string' ? c.note.slice(0, 400) : '',
      })).slice(0, 25)
    : [];
  const frequentTasks = Array.isArray(raw.frequentTasks)
    ? raw.frequentTasks.filter((t: any): t is FrequentTask => Boolean(t) && typeof t.phrase === 'string').map((t: any) => ({
        phrase: String(t.phrase).slice(0, 160),
        count: Math.round(num(t.count, 1, 1, 9999)),
        lastAt: num(t.lastAt, Date.now(), 0, 9999999999999),
      })).slice(0, 12)
    : [];
  const careContacts = Array.isArray(raw.careContacts)
    ? raw.careContacts.filter((c: any): c is CareContact => Boolean(c) && typeof c.name === 'string' && typeof c.phone === 'string').map((c: any) => ({
        id: typeof c.id === 'string' ? c.id.slice(0, 64) : `cc-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
        name: String(c.name).slice(0, 200),
        phone: String(c.phone).slice(0, 40),
      })).slice(0, 6)
    : [];
  return {
    ...DEFAULT_PROFILE,
    displayName: typeof raw.displayName === 'string' ? raw.displayName.slice(0, 200) : DEFAULT_PROFILE.displayName,
    accessibilityNeed: ['none', 'blind', 'low_vision', 'cognitive', 'motor', 'deaf_hard_of_hearing'].includes(raw.accessibilityNeed) ? raw.accessibilityNeed : DEFAULT_PROFILE.accessibilityNeed,
    verbosity: ['terse', 'normal', 'detailed'].includes(raw.verbosity) ? raw.verbosity : DEFAULT_PROFILE.verbosity,
    languageComplexity: ['simple', 'standard', 'technical'].includes(raw.languageComplexity) ? raw.languageComplexity : DEFAULT_PROFILE.languageComplexity,
    uiScale: num(raw.uiScale, 1, 0.8, 2.0),
    highContrast: Boolean(raw.highContrast),
    savedFields: strFields,
    corrections,
    frequentTasks,
    careContacts,
  };
}

// Serialised writes: concurrent onChangeText updates used to race and drop characters.
let settingsWrite: Promise<unknown> = Promise.resolve();
let profileWrite: Promise<unknown> = Promise.resolve();

function enqueueSettingsWrite(value: Settings): Promise<void> {
  const run = settingsWrite.then(() => AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(value)));
  settingsWrite = run.catch(() => {});
  return run;
}
function enqueueProfileWrite(value: UserProfile): Promise<void> {
  const run = profileWrite.then(() => AsyncStorage.setItem(PROFILE_KEY, JSON.stringify(value)));
  profileWrite = run.catch(() => {});
  return run;
}

export async function updateSettings(patch: Partial<Settings>): Promise<void> {
  const next = { ...state.settings, ...patch };
  // Clamp at write time so NaN/out-of-range never lives in memory until next load.
  next.speechRate = num(next.speechRate, 1.0, 0.5, 2.0);
  next.maxSteps = Math.round(num(next.maxSteps, 12, 3, 30));
  next.temperature = num(next.temperature, 0.2, 0, 1);
  if (typeof next.model === 'string' && !(GEMINI_MODEL_CHOICES as readonly string[]).includes(next.model)) {
    next.model = DEFAULT_SETTINGS.model;
  }
  set({ settings: next });
  await enqueueSettingsWrite(next).catch((err) => {
    console.warn('[profile] settings write failed:', err instanceof Error ? err.message : String(err));
    Alert.alert('Could not save settings', 'The settings change was kept in memory but could not be written to disk.');
  });
}

export async function updateProfile(patch: Partial<UserProfile>): Promise<void> {
  const next = { ...state.profile, ...patch };
  set({ profile: next });
  await enqueueProfileWrite(next).catch((err) => {
    console.warn('[profile] profile write failed:', err instanceof Error ? err.message : String(err));
    Alert.alert('Could not save', 'The change was kept in memory but could not be written to disk.');
  });
}

export async function updateSavedFields(patch: Partial<SavedFields>): Promise<void> {
  await updateProfile({ savedFields: { ...state.profile.savedFields, ...patch } });
}

/** The API key lives only in the Android Keystore, never in plaintext AsyncStorage. */
export async function setGeminiApiKey(key: string): Promise<boolean> {
  const trimmed = key.trim();
  if (!trimmed) {
    try {
      await SecureStore.deleteItemAsync(GEMINI_KEY_SECRET);
      set({ geminiApiKey: '', geminiKeyUncertain: false });
      return true;
    } catch (err) {
      Alert.alert('Could not remove the key', `The key store refused: ${err instanceof Error ? err.message : String(err)}.`);
      return false;
    }
  }
  try {
    await SecureStore.setItemAsync(GEMINI_KEY_SECRET, trimmed);
    set({ geminiApiKey: trimmed, geminiKeyUncertain: false });
    return true;
  } catch (err) {
    Alert.alert(
      'Could not save the key',
      `The secure key store refused the write: ${err instanceof Error ? err.message : String(err)}. The key was not changed.`,
    );
    return false;
  }
}

let tasksWrite: Promise<unknown> = Promise.resolve();
function enqueueTasksWrite(value: TaskRecord[]): Promise<void> {
  const run = tasksWrite.then(() => AsyncStorage.setItem(TASKS_KEY, JSON.stringify(value)));
  tasksWrite = run.catch(() => {});
  return run;
}

export function recordTask(record: TaskRecord): void {
  const next = [record, ...state.tasks.filter((t) => t.id !== record.id)].slice(0, 200);
  set({ tasks: next });
  enqueueTasksWrite(next).catch((err) => {
    console.warn('[profile] task write failed:', err instanceof Error ? err.message : String(err));
  });
}

export function clearTasks(): void {
  set({ tasks: [] });
  enqueueTasksWrite([]).catch((err) => {
    console.warn('[profile] clear tasks failed:', err instanceof Error ? err.message : String(err));
  });
}

export function removeCorrection(id: string): void {
  updateProfile({ corrections: state.profile.corrections.filter((c) => c.id !== id) }).catch(() => {});
}

export function noteCorrection(instruction: string, note: string): void {
  const correction: Correction = {
    id: `c${Date.now()}${Math.floor(Math.random() * 1000)}`,
    at: Date.now(),
    instruction: instruction.slice(0, 200),
    note: note.slice(0, 400),
  };
  updateProfile({ corrections: [correction, ...state.profile.corrections].slice(0, 25) }).catch(
    () => {},
  );
}

/**
 * Count a completed (or at least genuinely attempted) instruction phrase so the Shopping tab
 * can surface "do it again" shortcuts. Matched case-insensitively on the trimmed phrase;
 * capped so the profile blob stays small.
 */
export function recordFrequentTask(phrase: string): void {
  const trimmed = phrase.trim().slice(0, 160);
  if (!trimmed) return;
  const normalized = trimmed.toLowerCase();
  const existing = state.profile.frequentTasks;
  const match = existing.find((t) => t.phrase.toLowerCase() === normalized);
  const next = (
    match
      ? existing.map((t) =>
          t.phrase.toLowerCase() === normalized ? { ...t, count: t.count + 1, lastAt: Date.now() } : t,
        )
      : [{ phrase: trimmed, count: 1, lastAt: Date.now() }, ...existing]
  )
    .sort((a, b) => b.count - a.count || b.lastAt - a.lastAt)
    .slice(0, 12);
  updateProfile({ frequentTasks: next }).catch(() => {});
}

