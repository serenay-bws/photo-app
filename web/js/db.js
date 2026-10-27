// Opslag op het toestel zelf (IndexedDB). Er gaat niets naar een server.

const DB_NAME = "fotostudio";
let dbPromise = null;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        db.createObjectStore("photos", { keyPath: "id" });
        db.createObjectStore("blobs");
        db.createObjectStore("presets", { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    // vraag de browser de foto's niet zomaar op te ruimen
    navigator.storage?.persist?.().catch(() => {});
  }
  return dbPromise;
}

async function tx(store, mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    let result;
    Promise.resolve(fn(s)).then((r) => (result = r));
    t.oncomplete = () => resolve(result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error("Opslaan mislukt (is de opslag vol?)"));
  });
}

const req2p = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });

export const db = {
  all: (store) => tx(store, "readonly", (s) => req2p(s.getAll())),
  get: (store, key) => tx(store, "readonly", (s) => req2p(s.get(key))),
  put: (store, value, key) => tx(store, "readwrite", (s) => req2p(key === undefined ? s.put(value) : s.put(value, key))),
  del: (store, key) => tx(store, "readwrite", (s) => req2p(s.delete(key))),
};
