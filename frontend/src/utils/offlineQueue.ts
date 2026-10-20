/** Phase 4.1 — IndexedDB offline queue: mutations wait, then sync when online.
 * Also stores recovered mic drafts: a recording interrupted by an unmount or
 * page leave is parked here so the next load can transcribe + send it. */
const DB = 'adaptiveai-offline';
const STORE = 'queue';
const DRAFTS = 'drafts';
const DRAFT_KEY = 'mic-draft';
const DB_VERSION = 2;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { autoIncrement: true });
      }
      if (!db.objectStoreNames.contains(DRAFTS)) {
        db.createObjectStore(DRAFTS);
      }
    };
    req.onsuccess = () => {
      const db = req.result;
      db.onversionchange = () => db.close();
      resolve(db);
    };
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(req.error ?? new Error('IDB blocked'));
  });
}

const MAX_QUEUE = 100;

export async function enqueueMutation(entry: { url: string; method: string; body: unknown }): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const countReq = store.count();
    countReq.onsuccess = () => {
      try {
        if ((countReq.result ?? 0) >= MAX_QUEUE) {
          // Evict oldest to bound growth on long outages.
          const cur = store.openCursor();
          cur.onsuccess = () => {
            const c = cur.result;
            if (c) { c.delete(); }
          };
        }
        store.add({ ...entry, ts: Date.now() });
      } catch (e) {
        reject(e as Error);
        return;
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error('IDB abort'));
  });
  db.close();
}

export type DrainOutcome = 'ok' | 'retry' | 'drop';

export async function drainQueue(sender: (e: { url: string; method: string; body: unknown }) => Promise<DrainOutcome>): Promise<number> {
  const db = await openDb();
  const items: { key: IDBValidKey; value: { url: string; method: string; body: unknown } }[] = await new Promise(
    (resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const store = tx.objectStore(STORE);
      const req = store.getAll();
      const keyReq = store.getAllKeys();
      const done = () => {
        if (req.readyState === 'done' && keyReq.readyState === 'done') {
          const pairs: { key: IDBValidKey; value: { url: string; method: string; body: unknown } }[] = [];
          const values = req.result as unknown[];
          for (let i = 0; i < values.length; i++) {
            const key: IDBValidKey | undefined = keyReq.result[i];
            if (key !== undefined) pairs.push({ key, value: values[i] as never });
          }
          resolve(pairs);
        }
      };
      req.onsuccess = done;
      keyReq.onsuccess = done;
      req.onerror = () => reject(req.error);
      keyReq.onerror = () => reject(keyReq.error);
      tx.onerror = () => reject(tx.error);
    },
  );
  let sent = 0;
  try {
    for (const { key, value } of items) {
      // 'ok' and 'drop' (poison 4xx) both leave the queue; only 'retry'
      // (offline/5xx) stops the drain so nothing behind a dead network is lost.
      // A sender that throws (offline exception instead of returning 'retry')
      // is a retry too - it must not abort the drain mid-loop.
      let outcome: DrainOutcome;
      try {
        outcome = await sender(value);
      } catch {
        outcome = 'retry';
      }
      if (outcome === 'retry') break;
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).delete(key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
      // Only actually-delivered mutations count as sent: poison-dropped 4xx
      // entries must never be reported as synced.
      if (outcome === 'ok') sent += 1;
    }
  } finally {
    db.close();
  }
  return sent;
}

/** Park an interrupted recording. The readwrite transaction below is atomic
 * and serialized, so a StrictMode double-mount (or any concurrent reader)
 * can never both take the same draft. */
export async function saveAudioDraft(blob: Blob): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(DRAFTS, 'readwrite');
    tx.objectStore(DRAFTS).put(blob, DRAFT_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function takeAudioDraft(): Promise<Blob | null> {
  const db = await openDb();
  try {
    return await new Promise<Blob | null>((resolve, reject) => {
      const tx = db.transaction(DRAFTS, 'readwrite');
      const store = tx.objectStore(DRAFTS);
      const getReq = store.get(DRAFT_KEY);
      getReq.onsuccess = () => {
        const value = (getReq.result as Blob | undefined) ?? null;
        // Resolve only once the delete commits: resolving on read while the
        // delete later fails would hand the same draft out twice.
        const delReq = store.delete(DRAFT_KEY);
        delReq.onsuccess = () => resolve(value);
        delReq.onerror = () => reject(delReq.error);
      };
      getReq.onerror = () => reject(getReq.error);
    });
  } finally {
    db.close();
  }
}

/** Deliberate discard (Escape): the parked draft must not resurface later. */
export async function clearAudioDraft(): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(DRAFTS, 'readwrite');
    tx.objectStore(DRAFTS).delete(DRAFT_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}
