// Execute shipped modules with a small DOM fake. No browser, dependencies or real mailbox.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (name) => fs.readFileSync(path.join(root, name), "utf8");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.events = {}; this.attributes = {}; this.value = ""; this.className = ""; this.text = ""; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.text = ""; this.children = items; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((n) => n.textContent).join(""); }
  set innerHTML(value) { assert(value.startsWith("<svg"), "Only constant SVG markup may use HTML"); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(key, fn) { this.events[key] = fn; }
  get classList() { return { add() {}, remove() {}, toggle() {} }; }
  querySelectorAll(selector) { const tags = selector.split(",").map((s) => s.trim()); const all = this.children.flatMap((n) => [n, ...n.querySelectorAll("*")]); return selector === "*" ? all : all.filter((n) => tags.includes(n.tag)); }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
}
async function environment(language) {
  const elements = new Map();
  const body = new Element("body");
  const document = { body, documentElement: {}, addEventListener() {},
    createElement: (tag) => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
    getElementById: (id) => { if (!elements.has(id)) elements.set(id, new Element("div")); return elements.get(id); } };
  const ctx = vm.createContext({ document, navigator: { language, onLine: true }, window: { confirm: () => true }, console, setTimeout, clearTimeout });
  vm.runInContext(source("assets/i18n.js"), ctx);
  const applications = [
    { id: "a".repeat(24), company: "Example", title: "UX Designer", job_id: "j", candidates: [{ id: "j" }], confirmed: true, match_state: "matched", status: "interview", last_event_at: "2026-11-20T10:00:00Z" },
    { id: "b".repeat(24), company: "Closed", title: "HMI Designer", confirmed: true, match_state: "unmatched", status: "rejected", last_event_at: "2026-11-19T10:00:00Z" },
    { id: "c".repeat(24), company: "Review", title: "", confirmed: false, match_state: "review", status: "unknown", candidates: [{ id: "j" }], last_event_at: "2026-11-18T10:00:00Z" },
  ];
  let failed = false, saved, posts = [], refreshes = 0, gate, writes = 0;
  const fetcher = async (route, options) => {
    if (gate) { await gate; gate = null; }
    if (failed) throw new Error("network");
    if (options?.method === "POST") { posts.push([route, JSON.parse(options.body)]); return { ok: true }; }
    if (route === "/api/applications") return { applications, sync: { enabled: true, status: "ok" } };
    return { application: { ...applications.find((a) => route.endsWith(a.id)),
      events: [{ subject: '<img src=x onerror=alert(1)>', excerpt: '<script>untrusted</script>', received_at: "2026-11-20T10:00:00Z", sender: "mail@example.org", confidence: "high", source: "mail" }] } };
  };
  const api = new vm.SyntheticModule(["request"], function () { this.setExport("request", fetcher); }, { context: ctx });
  const offline = new vm.SyntheticModule(["readApplicationsSnapshot", "saveApplicationsSnapshot"], function () {
    this.setExport("readApplicationsSnapshot", async () => saved);
    this.setExport("saveApplicationsSnapshot", async (value) => { saved = value; writes++; });
  }, { context: ctx });
  const ui = new vm.SourceTextModule(source("assets/ui.js"), { context: ctx });
  await ui.link(() => { throw new Error("Unexpected import"); });
  const module = new vm.SourceTextModule(source("assets/applications.js"), { context: ctx });
  await module.link((name) => name.includes("api.js") ? api : name.includes("offline.js") ? offline : ui);
  await module.evaluate();
  const view = module.namespace.createApplicationsView({ getJobs: () => [{ id: "j", company: "Example", title: "UX Designer", user_status: "saved" }], getCsrf: () => "fictional-csrf", onOpenJob() {}, onDataChanged() { refreshes++; } });
  await view.refresh();
  return { ctx, body, elements, applications, view, posts, setFailed: () => { failed = true; }, getWrites: () => writes,
    pauseNext() { let release; gate = new Promise((resolve) => { release = resolve; }); return release; } };
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
for (const language of ["de-DE", "en-US"]) {
  const env = await environment(language);
  const english = language === "en-US";
  const panel = env.elements.get("applications-panel");
  const find = (tag, label) => panel.querySelectorAll(tag).find((n) => n.textContent === label);
  const rows = () => panel.querySelectorAll("button").filter((n) => n.className === "application-row");
  assert.equal(rows().length, 2, "Unconfirmed mail does not appear among confirmed applications");
  assert.equal(env.elements.get("nav-applications-count").textContent, "2", "Navigation counts all confirmed applications, including rejections");
  const count = panel.querySelectorAll("span").find((node) => node.className === "header-job-count applications-count");
  const search = panel.querySelectorAll("input").find((node) => node.type === "search");
  assert.equal(count.attributes["aria-label"], english ? "2 Applications" : "2 Bewerbungen");
  assert(panel.querySelectorAll("label").some((node) => node.className === "search-field"), "Applications reuse the main search field");
  assert(panel.querySelectorAll("div").some((node) => node.className === "search-line"), "Count, search and actions share the standard header row");
  search.value = "Closed";
  search.events.input();
  assert.equal(rows().length, 1);
  assert.equal(count.attributes["aria-label"], english ? "1 Application" : "1 Bewerbung", "Header count follows search results");
  assert.equal(env.elements.get("nav-applications-count").textContent, "2", "Navigation retains the overall total");
  search.value = "no matching employer";
  search.events.input();
  assert.equal(count.children[0].textContent, "0");
  search.value = "";
  search.events.input();
  const add = panel.querySelectorAll("button").find((node) => node.attributes["aria-label"] === (english ? "Add application" : "Bewerbung erfassen"));
  assert.equal(add.className, "export-button", "Header actions reuse the standard round icon button");
  assert.equal(add.children[0].tag, "svg");
  await add.events.click();
  assert.equal(env.body.children[0].open, true, "The add icon opens manual entry");
  env.body.children[0].close();
  assert(rows()[0].textContent.includes(english ? "Interviewing" : "Im Gespräch"));
  await find("button", english ? "Needs review" : "Zu prüfen").events.click();
  assert.equal(rows().length, 1);
  assert.equal(count.children[0].textContent, "1", "Header count follows the selected status filter");
  assert.equal(env.elements.get("nav-applications-count").textContent, "2", "Navigation total is independent of the selected filter");
  await rows()[0].events.click();
  const dialog = env.body.children[0];
  const selects = dialog.querySelectorAll("select");
  assert.equal(dialog.querySelectorAll("span").find((node) => node.className === "application-status").dataset.status, "unknown");
  assert.equal(dialog.querySelectorAll("label").filter((node) => node.className === "application-field-wide").length, 2, "Listing assignment and status each have a full-width row");
  assert.equal(selects[0].value, "", "A matching suggestion requires confirmation");
  assert(dialog.textContent.includes("<script>untrusted</script>"), "Mail text remains inert text");
  const form = dialog.querySelectorAll("form")[0];
  await form.events.submit({ preventDefault() {} });
  assert.equal(env.posts.length, 1);
  assert.equal(env.posts[0][1].confirmed, true);
  assert.equal(env.posts[0][1].job_id, "");
  assert.equal(dialog.open, false);
  env.setFailed();
  await env.view.refresh();
  assert(panel.textContent.includes(english ? "Offline:" : "Offline:"));
  await rows()[0].events.click();
  assert(dialog.querySelectorAll("input, select, textarea, button").filter((n) => n !== dialog.querySelectorAll("button")[0]).every((n) => n.disabled), "Editing is disabled offline");
  assert(!dialog.textContent.includes("untrusted"), "Mail bodies are not loaded offline");
}
assert(!source("assets/applications.js").includes(".innerHTML"), "Mail UI uses textContent throughout");
const failedSync = await environment("de-DE");
failedSync.setFailed();
const syncControl = failedSync.elements.get("applications-panel").querySelectorAll("button").find((node) => node.attributes["aria-label"] === "Mails abgleichen");
await syncControl.events.click();
assert.equal(syncControl.attributes["aria-busy"], "false", "A failed sync restores the idle icon state");
assert.equal(syncControl.children[0].tag, "svg");
const colourStates = await environment("de-DE");
for (const status of ["submitted", "reviewing", "interview", "offer", "rejected", "withdrawn"]) {
  colourStates.applications[0].status = status;
  await colourStates.view.refresh();
  const row = colourStates.elements.get("applications-panel").querySelectorAll("button").find((node) => node.className === "application-row");
  assert.equal(row.querySelectorAll("span").find((node) => node.className === "application-status").dataset.status, status);
  await row.events.click();
  const detail = colourStates.body.children[0];
  const assignment = detail.querySelectorAll("select")[0];
  const selected = assignment.children.find((option) => option.value === "j");
  assert.equal(selected.textContent, "Example · UX Designer", "An assigned listing is shown without redundant suggestion/bookmark labels");
  assert.equal(detail.querySelectorAll("span").find((node) => node.className === "application-status").dataset.status, status, "List and detail use the same status colour code");
  detail.close();
}
const finished = await environment("de-DE");
for (const app of finished.applications) if (app.confirmed) app.status = "rejected";
await finished.view.refresh();
assert.equal(finished.elements.get("nav-applications-count").textContent, "2", "Completed applications remain in the total even when none are open");
assert.equal(finished.elements.get("nav-applications-count").hidden, false);
const logout = await environment("de-DE");
const writesBefore = logout.getWrites();
const release = logout.pauseNext();
const inflight = logout.view.refresh();
const suspended = logout.view.suspend();
release();
await Promise.all([inflight, suspended]);
await logout.view.refresh();
assert.equal(logout.getWrites(), writesBefore, "Logout blocks pending and future cache writes before clearing storage");
assert(source("assets/app.js").indexOf("await applicationsView.suspend()") < source("assets/app.js").indexOf("await clearOfflineData()"));
assert(source("sw.js").includes('"/assets/applications.js?v=8"'));
assert(source("assets/styles.css").includes('.top-nav [data-tab="applications"] .nav-count{display:inline-flex}'), "Application total remains visible on mobile");
console.log("Application UI checks passed: DE/EN, counts, filters, explicit matches, safe evidence, save, offline.");
