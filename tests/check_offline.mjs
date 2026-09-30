// No browser, npm or external dependency. Test the deployed modules against small explicit fakes.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (name) => fs.readFileSync(path.join(root, name), "utf8");
const languageCtx = vm.createContext({ navigator: { language: "de-DE" }, window: {},
  document: { documentElement: {}, addEventListener() {} } });
vm.runInContext(source("assets/i18n.js"), languageCtx);
const { t, locale } = languageCtx.window.JobfindI18n;
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

// The count follows the exact rendered selection, including tab/filter/optimistic changes.
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, { value: "all", attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; } });
  return elements.get(id);
};
element("search").value = "";
element("score-filter").value = "0";
element("visibility-filter").value = "visible";
element("sort-filter").value = "newest";
const cardGrid = { cards: [], replaceChildren(fragment) { this.cards = fragment.cards; }, querySelectorAll() { return []; } };
const viewCtx = vm.createContext({
  t, locale,
  state: { tab: "all", meta: {}, offline: true, jobs: [
    { id: "a", title: "Design", company: "Example", user_status: "saved", first_seen_at: "2026-09-30" },
    { id: "b", title: "Archive", company: "Example", user_status: "new", historical: true, first_seen_at: "2026-09-29" },
    { id: "c", title: "Product", company: "Other", user_status: "new", first_seen_at: "2026-09-28" },
    { id: "d", title: "Hidden", company: "Other", user_status: "hidden", first_seen_at: "2026-09-27" },
  ] },
  $: element, grid: cardGrid, mutationPending: false, syncInFlight: false,
  document: { createDocumentFragment: () => ({ cards: [], append(card) { this.cards.push(card); } }) },
  createCard: (job) => job, shortDate: () => "", updateRunNote() {}, updateOfflineState() {},
  openJob() {}, changeStatus() {}, askDelete() {}, changeLike() {},
});
vm.runInContext(functionText("filteredJobs", "updateRunNote") + "\n" + functionText("updateSummary", "render") + "\n" + functionText("render", "openJob"), viewCtx);
const checkCount = (tab, count) => {
  viewCtx.state.tab = tab;
  vm.runInContext("render()", viewCtx);
  assert.equal(cardGrid.cards.length, count);
  assert.equal(element("header-job-count").textContent, `${count} ${count === 1 ? "Job" : "Jobs"}`);
  assert.match(element("header-job-count").attributes["aria-label"], /in dieser Auswahl/);
};
checkCount("all", 3);
checkCount("saved", 1);
checkCount("history", 1);
element("search").value = "not present";
checkCount("all", 0);
element("search").value = "other";
checkCount("all", 1);
element("search").value = "";
element("visibility-filter").value = "hidden";
checkCount("all", 1);
element("visibility-filter").value = "visible";
viewCtx.state.jobs = viewCtx.state.jobs.filter((job) => job.id !== "a");
checkCount("saved", 0);
assert.equal(element("nav-saved-count").hidden, true);
checkCount("all", 2);
vm.runInContext("updateSummary()", viewCtx);
assert.equal(element("header-job-count").textContent, "2 Jobs", "Background refresh preserves the selected count");

// Disclosure behavior uses existing DOM events, without a menu library or browser run.
const menuListeners = new Map();
const documentListeners = new Map();
const buttonListeners = new Map();
const mediaListeners = new Map();
const menuClasses = new Set();
const infoButton = { attributes: {}, focused: false,
  setAttribute(name, value) { this.attributes[name] = value; }, focus() { this.focused = true; },
  addEventListener(name, fn) { buttonListeners.set(name, fn); } };
const infoActions = {
  classList: { contains: (name) => menuClasses.has(name), remove: (name) => menuClasses.delete(name),
    toggle(name) { if (menuClasses.has(name)) { menuClasses.delete(name); return false; } menuClasses.add(name); return true; } },
  contains: (target) => target === infoButton || target === infoActions,
  addEventListener(name, fn) { menuListeners.set(name, fn); },
};
const mobileMedia = { matches: true, addEventListener(name, fn) { mediaListeners.set(name, fn); } };
const menuCtx = vm.createContext({
  $: (id) => id === "header-actions" ? infoActions : infoButton,
  window: { matchMedia: () => mobileMedia },
  document: { addEventListener(name, fn) { documentListeners.set(name, fn); } },
});
vm.runInContext(functionText("setupHeaderInfoMenu", "setupFilterPanel") + "\nsetupHeaderInfoMenu();", menuCtx);
buttonListeners.get("click")();
assert.equal(infoButton.attributes["aria-expanded"], "true");
documentListeners.get("click")({ target: infoButton });
assert.equal(menuClasses.has("is-open"), true, "Inside clicks must not immediately close the dropdown");
documentListeners.get("click")({ target: {} });
assert.equal(infoButton.attributes["aria-expanded"], "false");
buttonListeners.get("click")();
documentListeners.get("keydown")({ key: "Escape", preventDefault() {} });
assert.equal(infoButton.focused, true);
assert.equal(menuClasses.has("is-open"), false);
buttonListeners.get("click")();
menuListeners.get("focusout")({ relatedTarget: {} });
assert.equal(menuClasses.has("is-open"), false);
buttonListeners.get("click")();
mobileMedia.matches = false;
mediaListeners.get("change")();
assert.equal(infoButton.attributes["aria-expanded"], "false");

// Native details stays open while adjusting filters, but dismisses outside or with Escape.
const filterDocumentListeners = new Map();
const filterListeners = new Map();
const filterTrigger = { focused: false, focus() { this.focused = true; } };
const filterSelect = {};
const filterPanel = { open: true, querySelector: () => filterTrigger,
  contains: (target) => [filterPanel, filterTrigger, filterSelect].includes(target),
  addEventListener(name, fn) { filterListeners.set(name, fn); } };
const filterCtx = vm.createContext({
  $: () => filterPanel,
  document: { addEventListener(name, fn) { filterDocumentListeners.set(name, fn); } },
});
vm.runInContext(functionText("setupFilterPanel", "filteredJobs") + "\nsetupFilterPanel();", filterCtx);
filterDocumentListeners.get("click")({ target: filterSelect });
assert.equal(filterPanel.open, true, "Changing a filter must not dismiss the panel");
filterDocumentListeners.get("click")({ target: filterTrigger });
assert.equal(filterPanel.open, true, "Native summary toggle must not be intercepted");
filterDocumentListeners.get("click")({ target: {} });
assert.equal(filterPanel.open, false, "Outside tap closes the filter panel");
filterPanel.open = true;
filterDocumentListeners.get("keydown")({ key: "Escape", preventDefault() {} });
assert.equal(filterPanel.open, false);
assert.equal(filterTrigger.focused, true);
filterPanel.open = true;
filterListeners.get("focusout")({ relatedTarget: filterSelect });
assert.equal(filterPanel.open, true);
filterListeners.get("focusout")({ relatedTarget: {} });
assert.equal(filterPanel.open, false, "Keyboard navigation outside closes the panel");

// Offline preparation and a healthy offline snapshot stay quiet; pending work/errors do not.
const note = { hidden: false, textContent: "stale", classList: { toggle() {} } };
const undo = { disabled: false };
const statusCtx = vm.createContext({
  t,
  state: { offline: false, offlineReady: false, pendingActions: [], syncError: "" },
  syncInFlight: false, mutationPending: false,
  $: (id) => id === "offline-state" ? note : undo,
  document: { body: { classList: { toggle() {} } } },
});
vm.runInContext(functionText("updateOfflineState", "queueOfflineCopy"), statusCtx);
const updateStatusNote = () => vm.runInContext("updateOfflineState()", statusCtx);
for (const [offline, ready] of [[false, false], [false, true], [true, true]]) {
  Object.assign(statusCtx.state, { offline, offlineReady: ready });
  updateStatusNote();
  assert.equal(note.hidden, true, "Routine offline status must stay hidden");
  assert.equal(note.textContent, "");
}
statusCtx.state.pendingActions = [{ id: 1 }];
updateStatusNote();
assert.equal(note.hidden, false);
assert.match(note.textContent, /1 Änderung lokal gespeichert/);
statusCtx.state.offline = false;
updateStatusNote();
assert.match(note.textContent, /wartet auf Übertragung/);
statusCtx.syncInFlight = true;
updateStatusNote();
assert.match(note.textContent, /wird übertragen/);
assert.equal(undo.disabled, true);
statusCtx.syncInFlight = false;
statusCtx.state.pendingActions = [];
statusCtx.state.syncError = "Übertragung fehlgeschlagen";
updateStatusNote();
assert.equal(note.hidden, false);
assert.equal(note.textContent, statusCtx.state.syncError);
statusCtx.state.syncError = "";
updateStatusNote();
assert.equal(note.hidden, true);
assert.equal(undo.disabled, false);

const queueCtx = vm.createContext({ console, t });
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
const appPath = source("index.html").match(/src="([^\"]*\/app\.js\?v=\d+)"/)[1];
assert(source("sw.js").includes(`"${appPath}"`), "Shell must cache the current app entry point");
const stylesPath = source("index.html").match(/href="([^\"]*\/styles\.css\?v=\d+)"/)[1];
assert(source("sw.js").includes(`"${stylesPath}"`), "Shell must cache the current stylesheet");
console.log("UI/offline checks passed: filter dismissal, selected counts, info dropdown, quiet status, atomic storage, ordered retry, undo, auth boundary, logout, shell.");
