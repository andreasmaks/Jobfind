const DATABASE = "jobfind-offline-v1";
const STORE = "snapshots";
const ACTIONS = "pending-actions";
const CACHE_PREFIX = "jobfind-";
const LOGO_CACHE = "jobfind-logos-v1";

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 2);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE);
      if (!request.result.objectStoreNames.contains(ACTIONS)) {
        request.result.createObjectStore(ACTIONS, { keyPath: "id", autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function snapshotTransaction(mode, operation) {
  const database = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE, mode);
      const request = operation(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request?.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
}

export async function readSnapshot() {
  const snapshot = await snapshotTransaction("readonly", (store) => store.get("latest"));
  return snapshot && Array.isArray(snapshot.jobs) && snapshot.meta && snapshot.savedAt
    ? snapshot : null;
}

export async function readPendingActions() {
  const database = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(ACTIONS, "readonly");
      const request = transaction.objectStore(ACTIONS).getAll();
      transaction.oncomplete = () => resolve(request.result || []);
      transaction.onerror = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
}

export async function savePendingAction(action, jobs, meta) {
  const database = await openDatabase();
  const savedAt = new Date().toISOString();
  try {
    const id = await new Promise((resolve, reject) => {
      const transaction = database.transaction([STORE, ACTIONS], "readwrite");
      const request = transaction.objectStore(ACTIONS).add(action);
      transaction.objectStore(STORE).put({ jobs, meta, savedAt }, "latest");
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
    return { id, savedAt };
  } finally {
    database.close();
  }
}

export async function removePendingAction(id) {
  const database = await openDatabase();
  try {
    await new Promise((resolve, reject) => {
      const transaction = database.transaction(ACTIONS, "readwrite");
      transaction.objectStore(ACTIONS).delete(id);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
}

async function writeSnapshot(jobs, meta) {
  const savedAt = new Date().toISOString();
  await snapshotTransaction("readwrite", (store) => store.put({ jobs, meta, savedAt }, "latest"));
  return savedAt;
}

async function cacheDynamicLogos(jobs) {
  const urls = [...new Set(jobs.map((job) => job.company_logo_url).filter((url) =>
    typeof url === "string" && /^\/assets\/company-logos\/[0-9a-f]{24}\.png(?:\?v=\d+)?$/.test(url)))];
  const cache = await caches.open(LOGO_CACHE);
  for (let index = 0; index < urls.length; index += 4) {
    await Promise.all(urls.slice(index, index + 4).map(async (url) => {
      try {
        if (await cache.match(url)) return;
        const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
        if (response.ok && !response.redirected && response.headers.get("Content-Type")?.startsWith("image/")) {
          await cache.put(url, response);
        }
      } catch (_) {
        // A missing logo falls back to the building symbol in the offline view.
      }
    }));
  }
}

export async function prepareOffline(jobs, meta) {
  if (!("serviceWorker" in navigator) || !("indexedDB" in window) || !("caches" in window)) {
    throw new Error("Offline storage is unavailable");
  }
  await navigator.serviceWorker.register("/sw.js");
  let timeout;
  try {
    await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error("Offline app installation timed out")), 15000);
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
  let shellReady = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const shell = await caches.open("jobfind-shell-v5");
    if (await shell.match("/")) {
      shellReady = true;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!shellReady) throw new Error("Offline app shell is incomplete");
  const savedAt = await writeSnapshot(jobs, meta);
  await cacheDynamicLogos(jobs);
  return savedAt;
}

export async function clearOfflineData() {
  if ("indexedDB" in window) {
    const database = await openDatabase();
    try {
      await new Promise((resolve, reject) => {
        const transaction = database.transaction([STORE, ACTIONS], "readwrite");
        const pending = transaction.objectStore(ACTIONS);
        const count = pending.count();
        count.onsuccess = () => {
          if (count.result) {
            transaction.abort();
            return;
          }
          transaction.objectStore(STORE).clear();
          pending.clear();
        };
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error || new Error("Pending offline changes must sync before logout"));
      });
    } finally {
      database.close();
    }
  }
  if ("serviceWorker" in navigator) {
    const registration = await navigator.serviceWorker.getRegistration("/");
    if (registration) await registration.unregister();
  }
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX)).map((key) => caches.delete(key)));
  }
}
