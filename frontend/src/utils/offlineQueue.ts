/** Phase 4.1 — IndexedDB offline queue: mutations wait, then sync when online. */
const DB = 'adaptiveai-offline';
const STORE = 'queue';

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function enqueueMutation(entry: { url: string; method: string; body: unknown }): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).add({ ...entry, ts: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
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
          resolve((req.result as never[]).map((v, i) => ({ key: keyReq.result[i], value: v as never })));
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
  for (const { key, value } of items) {
    // 'ok' and 'drop' (poison 4xx) both leave the queue; only 'retry'
    // (offline/5xx) stops the drain so nothing behind a dead network is lost.
    const outcome = await sender(value);
    if (outcome === 'retry') break;
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    sent += 1;
  }
  db.close();
  return sent;
}
