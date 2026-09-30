// No browser, npm or external dependency. Test the deployed modules against small explicit fakes.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (name) => fs.readFileSync(path.join(root, name), "utf8");
const clone = structuredClone;
const stores = new Map();
let failCommit = false;
let cacheClears = 0;
let unregistered = 0;
let nextId = 1;
const db = {
  objectStoreNames: { contains: (name) => stores.has(name) },
  createObjectStore(name) { stores.set(name, new Map()); },
  close() {},
  transaction(names, mode) {
    const selected = Array.isArray(names) ? names : [names];
    const working = new Map(selected.map((name) => [name, new Map([...stores.get(name)].map(([key, value]) => [key, clone(value)]))]));
    const tx = {
      aborted: false,
      abort() { tx.aborted = true; tx.error = new Error("abort"); queueMicrotask(() => tx.onabort?.()); },
      objectStore(name) {
        const data = working.get(name);
        const request = (result) => ({ result });
        return {
          get: (key) => request(clone(data.get(key))),
          getAll: () => request([...data.values()].map((value) => clone(value))),
          put(value, key) { data.set(key, clone(value)); return request(key); },
          add(value) { const id = nextId++; data.set(id, clone({ ...value, id })); return request(id); },
          delete(key) { data.delete(key); return request(undefined); },
          clear() { data.clear(); return request(undefined); },
          count() { const req = request(data.size); queueMicrotask(() => req.onsuccess?.()); return req; },
        };
      },
    };
    setImmediate(() => {
      if (tx.aborted) return;
      if (failCommit && mode === "readwrite") { failCommit = false; tx.abort(); return; }
      if (mode === "readwrite") for (const [name, data] of working) stores.set(name, data);
      tx.oncomplete?.();
    });
    return tx;
  },
};
const indexedDB = {
  open() {
    const request = { result: db };
    setImmediate(() => {
      if (!stores.size) request.onupgradeneeded?.();
      request.onsuccess?.();
    });
    return request;
  },
};
const caches = {
  open: async () => ({ match: async () => true }),
  keys: async () => ["jobfind-shell-v3", "other-app-cache"],
  delete: async () => { cacheClears++; },
};
const navigator = { serviceWorker: {
  register: async () => {}, ready: Promise.resolve(),
  getRegistration: async () => ({ unregister: async () => { unregistered++; } }),
} };
const ctx = vm.createContext({ indexedDB, caches, navigator, window: { indexedDB, caches },
  setTimeout, clearTimeout, URL, console });
const offline = new vm.SourceTextModule(source("assets/offline.js"), { context: ctx });
await offline.link(() => { throw new Error("Unexpected import"); });
await offline.evaluate();
const api = new vm.SourceTextModule(source("assets/api.js"), { context: ctx });
await api.link(() => offline);
await api.evaluate();
const o = offline.namespace;
assert.equal(await o.readSnapshot(), null);
assert.equal((await o.readPendingActions()).length, 0);
await o.prepareOffline([{ id: "a", title: "Fictional" }], { total: 1 });
assert.equal((await o.readSnapshot()).jobs[0].id, "a");
const first = await o.savePendingAction({ kind: "delete", jobId: "a" }, [], { total: 0 });
await o.savePendingAction({ kind: "restore", jobId: "a", job: { id: "a" } }, [{ id: "a" }], { total: 1 });
assert.equal((await o.readPendingActions()).length, 2);
failCommit = true;
await assert.rejects(o.savePendingAction({ kind: "like", jobId: "a" }, [], { total: 0 }));
assert.equal((await o.readPendingActions()).length, 2, "Failed commit must keep existing queue");
assert.equal((await o.readSnapshot()).jobs.length, 1, "Queue + snapshot must roll back together");
await assert.rejects(o.clearOfflineData());
assert.equal(cacheClears, 0, "Pending changes must block logout cleanup");
await o.removePendingAction(first.id);
const pending = await o.readPendingActions();
assert.equal(pending[0].kind, "restore");
await o.removePendingAction(pending[0].id);
await o.clearOfflineData();
assert.equal(await o.readSnapshot(), null);
assert.equal(cacheClears, 1, "Only own caches removed");
assert.equal(unregistered, 1);

// API: network failure falls back to snapshot, authentication failure must never do so.
await o.prepareOffline([{ id: "a" }], { total: 1 });
ctx.fetch = async () => { throw new Error("network"); };
assert.equal((await api.namespace.loadPortal()).offline, true);
ctx.fetch = async () => ({ status: 401 });
ctx.window.location = { href: "" };
await assert.rejects(api.namespace.loadPortal(), (error) => error.authRequired);
assert.equal(ctx.window.location.href, "/login?next=/");
ctx.fetch = async (route) => ({ status: 200, ok: true, json: async () =>
  route.includes("jobs") ? { ok: true, jobs: [{ id: "a" }] } : route.includes("csrf") ? { ok: true, token: "fresh" } : { ok: true, total: 1 } });
assert.equal((await api.namespace.loadPortal()).csrf, "fresh");

// Exercise exact deployed queue functions; omit unrelated DOM startup.
const app = source("assets/app.js");
function functionText(name, nextName) {
  let start = app.indexOf(`function ${name}(`);
  assert(start >= 0);
  if (app.slice(start - 6, start) === "async ") start -= 6;
  const end = app.indexOf(`function ${nextName}(`, start);
  assert(end > start);
  return app.slice(start, end).replace(/async\s*$/, "").trim();
}
const funcs = functionText("applyPendingActions", "queueAction") + "\n" + functionText("syncPendingActions", "updateSummary");
const queueCtx = vm.createContext({ console });
const calls = [];
let failOn = "restore";
Object.assign(queueCtx, {
  state: { jobs: [], offline: false, pendingActions: [{ id: 1, kind: "delete" }, { id: 2, kind: "restore" }, { id: 3, kind: "like" }] },
  syncInFlight: false, mutationPending: false, render() {}, updateOfflineState() {}, queueOfflineCopy() {},
  sendAction: async (action) => { calls.push(action.kind); if (action.kind === failOn) throw Object.assign(new Error("network"), { networkFailure: true }); },
  removePendingAction: async () => {},
  loadPortal: async () => ({ jobs: [{ id: "a" }], meta: {}, offline: false, csrf: "fresh" }),
});
vm.runInContext(funcs, queueCtx);
assert.equal(await vm.runInContext("syncPendingActions()", queueCtx), false);
assert.deepEqual(calls, ["delete", "restore"]);
assert.equal(queueCtx.state.pendingActions.length, 2, "Failed and later actions retained in order");
failOn = "";
queueCtx.state.offline = false;
assert.equal(await vm.runInContext("syncPendingActions()", queueCtx), true);
assert.deepEqual(calls, ["delete", "restore", "restore", "like"]);
assert.equal(queueCtx.state.pendingActions.length, 0);
const merged = vm.runInContext(`applyPendingActions([{id:"a", user_status:"new"}], [
  {kind:"delete",jobId:"a"}, {kind:"restore",jobId:"a",job:{id:"a",user_status:"saved"}},
  {kind:"like",jobId:"a",liked:true}])`, queueCtx);
assert.equal(merged[0].user_status, "saved");
assert.equal(merged[0].liked, true);

// Service worker never intercepts writes, APIs or remote URLs. Shell install rejects redirected login.
const listeners = new Map();
const swCtx = vm.createContext({ URL, Response, console,
  self: { location: { origin: "http://localhost:8124" }, addEventListener: (name, fn) => listeners.set(name, fn), skipWaiting: async () => {}, clients: { claim: async () => {} } },
  caches: { open: async () => ({ put: async () => {} }) },
  fetch: async () => ({ ok: true, redirected: true }),
});
vm.runInContext(source("sw.js"), swCtx);
let install;
listeners.get("install")({ waitUntil(promise) { install = promise; } });
await assert.rejects(install, /Cannot cache/);
for (const request of [
  { method: "POST", url: "http://localhost:8124/api/jobs/a/delete" },
  { method: "GET", url: "http://localhost:8124/api/jobs" },
  { method: "GET", url: "https://example.org/" },
]) {
  listeners.get("fetch")({ request, respondWith() { throw new Error("Unexpected caching"); } });
}
console.log("Offline checks passed: atomic storage, ordered retry, undo, auth boundary, logout, shell.");
