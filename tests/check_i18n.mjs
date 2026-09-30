// Targeted language checks using shipped code, no browser or dependencies.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (name) => fs.readFileSync(path.join(root, name), "utf8");

class Node {
  constructor(tag = "text", text = "") { this.tag = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.className = ""; this.textContent = text; this.events = new Map(); }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((node) => node.textContent).join(""); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ""; this.children = nodes; }
  addEventListener(name, fn) { this.events.set(name, fn); }
  insertAdjacentHTML() {} // Constant SVG markup is unrelated to language selection.
  focus() { this.focused = true; }
  get childElementCount() { return this.children.filter((node) => node.tag !== "text").length; }
  get firstElementChild() { return this.children.find((node) => node.tag !== "text"); }
  get classList() {
    const self = this;
    const change = (name, enable) => { const names = new Set(self.className.split(" ").filter(Boolean)); enable ? names.add(name) : names.delete(name); self.className = [...names].join(" "); return enable; };
    return { add: (name) => change(name, true), remove: (name) => change(name, false),
      toggle: (name, force) => change(name, force ?? !self.className.split(" ").includes(name)) };
  }
}
function environment(preferred, page = "index.html", secondary = "de-DE") {
  const html = source(page);
  const body = html.split("<body")[1].replace(/^[^>]*>/, "");
  const texts = body.split(/<[^>]*>/).filter((text) => text.trim()).map((text) => new Node("text", text));
  const attributes = [...html.matchAll(/(aria-label|placeholder|title)="([^\"]*)"/g)].map((match) => {
    const node = new Node(); node.setAttribute(match[1], match[2]); return node;
  });
  const events = new Map();
  const label = new Node("span", "Hell");
  const button = new Node("button"); button.querySelector = () => label;
  const loginError = new Node("p", "Das Passwort war nicht richtig.");
  const password = new Node("input");
  const document = {
    body: {}, documentElement: { dataset: {} }, title: html.match(/<title>(.*?)<\/title>/)[1],
    createTreeWalker() { let index = 0; return { nextNode: () => texts[index++] }; },
    querySelectorAll: (selector) => selector === "[data-theme-toggle]" ? [button] : attributes,
    querySelector: () => new Node("meta"),
    createElement: (tag) => new Node(tag), createTextNode: (text) => new Node("text", text),
    getElementById: (id) => id === "login-error" ? loginError : password,
    addEventListener(name, fn) { if (!events.has(name)) events.set(name, []); events.get(name).push(fn); },
  };
  const ctx = vm.createContext({ document, navigator: { languages: [preferred, secondary], language: preferred },
    window: { location: { search: "?error=rate" } }, localStorage: { getItem: () => null, setItem() {} },
    URLSearchParams, Intl, Date, console });
  vm.runInContext(source("assets/i18n.js"), ctx);
  return { ctx, document, texts, attributes, events, button, label, loginError, password };
}

for (const preferred of ["de", "de-DE", "de-AT", "de-CH", "DE-de", "en-US", "fr-FR", "ja-JP"]) {
  for (const page of ["index.html", "login.html"]) {
    const env = environment(preferred, page);
    const { language, t, translatePage } = env.ctx.window.JobfindI18n;
    const german = /^de(?:-|$)/i.test(preferred);
    assert.equal(language, german ? "de" : "en");
    const original = env.texts.map((node) => node.textContent);
    translatePage();
    assert.equal(env.document.documentElement.lang, language);
    if (german) assert.deepEqual(env.texts.map((node) => node.textContent), original, "German HTML must stay unchanged");
    else {
      assert(env.texts.some((node) => node.textContent.trim() === (page === "index.html" ? "All" : "Password")));
      const unchanged = new Set(["jobfind", "Jobs", "Hybrid", "Details", "Optional"]);
      for (const text of original.map((text) => text.trim()).filter((text) => !unchanged.has(text))) assert.notEqual(t(text), text, `Untranslated HTML: ${text}`);
      for (const node of env.attributes) for (const value of Object.values(node.attributes)) assert(!/[äöüÄÖÜß]/.test(value), `Untranslated attribute: ${value}`);
    }
    // A second call must never translate subsequently rendered imported/job content.
    const imported = new Node("text", "Aufgaben"); env.texts.push(imported); translatePage();
    assert.equal(imported.textContent, "Aufgaben");
    assert.equal(t("{count} Jobs", { count: 2 }), german ? "2 Jobs" : "2 jobs");
    assert.equal(t("Stelle löschen: {title}", { title: "<b>Aufgaben</b>" }), german ? "Stelle löschen: <b>Aufgaben</b>" : "Delete job: <b>Aufgaben</b>");
    vm.runInContext(source("assets/theme.js"), env.ctx);
    for (const fn of env.events.get("DOMContentLoaded")) fn();
    assert.equal(env.label.textContent, german ? "Hell" : "Light");
    env.button.events.get("click")();
    assert.equal(env.label.textContent, german ? "Dunkel" : "Dark");
    assert.equal(env.button.getAttribute("aria-label"), german ? "Dunkles Design einschalten" : "Switch to dark appearance");
    vm.runInContext(source("assets/login.js"), env.ctx);
    assert.equal(env.loginError.textContent, t("Zu viele Versuche. Bitte warte kurz und versuche es erneut."));
  }
}

// Real card/details rendering: UI changes, imported text and action codes do not.
for (const preferred of ["de-DE", "fr-FR"]) {
  const env = environment(preferred);
  env.ctx.window.JobfindI18n.translatePage();
  const module = new vm.SourceTextModule(source("assets/ui.js"), { context: env.ctx });
  await module.link(() => { throw new Error("Unexpected import"); }); await module.evaluate();
  const german = preferred === "de-DE";
  const job = { id: "a", title: "Aufgaben", company: "Unternehmen", summary: "Gründe", fit: "Fachbereich",
    hours: "30–32 Stunden", remote: "Remote möglich", user_status: "new", score: 8,
    first_seen_at: new Date().toISOString(), original_url: "https://example.org/fictional", location: "Stuttgart",
    company_description: "Unternehmensangaben im Original", company_products: "Produkte im Original" };
  const cards = module.namespace.createCard(job, () => {}, () => {}, () => {}, () => {});
  const descendants = (node) => [node, ...node.children.flatMap(descendants)];
  assert(descendants(cards).some((node) => node.className === "card-title" && node.textContent === "Aufgaben"));
  assert(descendants(cards).some((node) => node.className === "company-name" && node.textContent === "Unternehmen"));
  assert(cards.textContent.includes(german ? "30–32 Std." : "30–32 hrs"));
  assert(cards.textContent.includes(german ? "Heute" : "Today"));
  assert(cards.textContent.includes(german ? "Anzeige öffnen" : "Open listing"));
  assert.equal(module.namespace.shortDate("2026-09-30"), new Intl.DateTimeFormat(german ? "de-DE" : "en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(new Date("2026-09-30")));
  const target = new Node("div"), save = new Node("button");
  const dialog = { querySelector: (selector) => selector === "#dialog-content" ? target : save, showModal() { this.open = true; } };
  module.namespace.showDetails(dialog, job, () => {});
  assert(target.textContent.includes(german ? "Über das Unternehmen" : "About the company"));
  assert(target.textContent.includes(german ? "Produkte & Dienstleistungen" : "Products & services"));
  assert(target.textContent.includes(job.company_description)); assert(target.textContent.includes(job.company_products));
  assert(target.textContent.includes(job.summary)); assert(target.textContent.includes(job.fit));
  assert.equal(save.getAttribute("aria-label"), german ? "Stelle merken" : "Save job");

  // Actual app count/queue/undo functions must use the same selected language offline.
  const app = source("assets/app.js");
  const functionText = (name, next) => app.slice(app.indexOf(`function ${name}(`), app.indexOf(`function ${next}(`));
  const elements = new Map();
  const get = (id) => { if (!elements.has(id)) elements.set(id, new Node()); return elements.get(id); };
  const state = { jobs: [job], meta: {}, pendingActions: [], syncError: "", offline: true };
  const appCtx = vm.createContext({ t: env.ctx.window.JobfindI18n.t, state, $: get,
    filteredJobs: () => state.jobs, shortDate: () => "", mutationPending: false, syncInFlight: false,
    document: { body: new Node() }, deletedJobs: [job] });
  vm.runInContext(functionText("updateSummary", "render") + functionText("updateOfflineState", "queueOfflineCopy") + functionText("deletionNotice", "askDelete"), appCtx);
  vm.runInContext("updateSummary(); updateOfflineState();", appCtx);
  assert.equal(get("header-job-count").textContent, german ? "1 Job" : "1 job");
  assert.equal(get("offline-state").hidden, true);
  state.pendingActions = [{ kind: "delete", jobId: "a" }, { kind: "like", jobId: "b" }];
  vm.runInContext("updateOfflineState(); deletionNotice();", appCtx);
  assert.equal(get("offline-state").textContent, german ? "2 Änderungen lokal gespeichert. Wird beim Verbinden übertragen." : "2 changes saved locally. They will sync when reconnected.");
  assert.equal(get("deletion-message").textContent, german ? "„Aufgaben“ gelöscht. Wird nach dem Verbinden übertragen." : "“Aufgaben” deleted. It will sync when reconnected.");
}
for (const page of ["index.html", "login.html"]) {
  assert(source(page).indexOf("/assets/i18n.js?v=1") < source(page).indexOf("/assets/theme.js?v=2"));
}
assert(source("sw.js").includes('"/assets/i18n.js?v=1"'));
assert(source("sw.js").includes('"jobfind-shell-v5"'));
assert(source("assets/offline.js").includes('"jobfind-shell-v5"'));
console.log("Language checks passed: primary preference, DE variants, English fallback, HTML/accessibility, theme, login errors, dates, cards/details, untouched job data, offline shell.");
