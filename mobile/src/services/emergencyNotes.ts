import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system';

const NOTES_KEY = 'adaptiveai.emergency-notes.v1';

export type EmergencyNote = {
  id: string;
  uri: string;
  at: number;
  durationMs?: number;
};

function isValidNote(n: any): n is EmergencyNote {
  return Boolean(n) && typeof n.id === 'string' && typeof n.uri === 'string' && typeof n.at === 'number' && Number.isFinite(n.at);
}

export async function loadEmergencyNotes(): Promise<EmergencyNote[]> {
  const raw = await AsyncStorage.getItem(NOTES_KEY).catch(() => null);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return (parsed as any[]).filter(isValidNote).slice(0, 50);
  } catch {
    return [];
  }
}

// Save/delete are read-modify-write cycles over one stored list. Run them through a serial
// queue: two concurrent calls each read the same stale list and the last writer silently dropped the other's
// change.
let writeQueue: Promise<unknown> = Promise.resolve();

function enqueueWrite<T>(task: () => Promise<T>): Promise<T> {
  const run = writeQueue.then(task, task);
  writeQueue = run.catch(() => {});
  return run;
}

export function saveEmergencyNote(note: EmergencyNote): Promise<void> {
  return enqueueWrite(async () => {
    const notes = await loadEmergencyNotes();
    const next = [note, ...notes].slice(0, 50);
    // Delete files of evicted notes so documentDirectory does not fill forever.
    const evicted = [note, ...notes].slice(50);
    await AsyncStorage.setItem(NOTES_KEY, JSON.stringify(next)).catch((e) => { console.warn('[emergencyNotes] save failed:', e); throw e; });
    for (const old of evicted) {
      await FileSystem.deleteAsync(old.uri, { idempotent: true }).catch(() => {});
    }
  });
}

export function deleteEmergencyNote(id: string): Promise<void> {
  return enqueueWrite(async () => {
    const notes = await loadEmergencyNotes();
    const target = notes.find((n) => n.id === id);
    await AsyncStorage.setItem(NOTES_KEY, JSON.stringify(notes.filter((note) => note.id !== id))).catch((e) => { console.warn('[emergencyNotes] delete failed:', e); throw e; });
    if (target?.uri) {
      await FileSystem.deleteAsync(target.uri, { idempotent: true }).catch(() => {});
    }
  });
}
