import { request } from "/assets/api.js?v=12";
import { readApplicationsSnapshot, saveApplicationsSnapshot } from "/assets/offline.js?v=21";
import { companyMark, displayJobTitle, shortDate, applicationStatusLabel } from "/assets/ui.js?v=7";

const { t } = window.JobfindI18n;
const closed = new Set(["rejected", "withdrawn"]);
const statuses = ["submitted", "reviewing", "interview", "offer", "rejected", "withdrawn"];
const node = (tag, className = "", text) => {
  const el = document.createElement(tag);
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
};
const button = (label, className, action) => {
  const el = node("button", className, t(label));
  el.type = "button";
  el.addEventListener("click", action);
  return el;
};

function statusBadge(app) {
  const status = node("span", "application-status", app.confirmed ? applicationStatusLabel(app.status) : t("Zu prüfen"));
  status.dataset.status = app.confirmed ? app.status : "unknown";
  return status;
}

export function createApplicationsView({ getJobs, getCsrf, onOpenJob, onDataChanged }) {
  const panel = document.getElementById("applications-panel");
  let data = { applications: [], sync: {} }, offline = false, loaded = false, loading = false;
  let filter = "all", query = "", pending = false, pollTimer, visible = false;
  let suspended = false, idle = Promise.resolve();
  const heading = node("div", "applications-heading");
  const titleBlock = node("div");
  titleBlock.append(node("p", "applications-eyebrow", t("DEIN NÄCHSTER SCHRITT")), node("h1", "", t("Bewerbungen")));
  const actions = node("div", "applications-actions");
  const syncButton = button("Mails abgleichen", "button-secondary", sync);
  const addButton = button("Bewerbung erfassen", "button-primary", () => openEditor());
  actions.append(syncButton, addButton);
  heading.append(titleBlock, actions);
  const summary = node("p", "applications-summary");
  const toolbar = node("div", "applications-toolbar");
  const filters = node("div", "applications-filters");
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", t("Bewerbungen filtern"));
  for (const [key, label] of [["all", "Alle"], ["open", "Offen"], ["review", "Zu prüfen"], ["closed", "Abgeschlossen"]]) {
    const control = button(label, "", () => { filter = key; render(); });
    control.dataset.filter = key;
    filters.append(control);
  }
  const searchLabel = node("label", "applications-search");
  searchLabel.append(node("span", "visually-hidden", t("Bewerbungen durchsuchen")));
  const search = node("input");
  search.type = "search";
  search.placeholder = t("Unternehmen oder Position suchen");
  search.addEventListener("input", () => { query = search.value.trim().toLocaleLowerCase(); render(); });
  searchLabel.append(search);
  toolbar.append(filters, searchLabel);
  const notice = node("p", "applications-notice");
  notice.setAttribute("role", "status");
  const list = node("div", "applications-list");
  const empty = node("div", "empty-state applications-empty");
  panel.append(heading, summary, toolbar, notice, list, empty);
  const dialog = node("dialog", "application-dialog");
  dialog.setAttribute("aria-labelledby", "application-dialog-title");
  document.body.append(dialog);
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => { if (visible) render(); });

  function render() {
    const confirmed = data.applications.filter((a) => a.confirmed);
    const review = data.applications.filter((a) => !a.confirmed || a.match_state === "review");
    const open = confirmed.filter((a) => !closed.has(a.status));
    summary.textContent = t("{total} Bewerbungen · {open} offen · {review} zu prüfen", { total: confirmed.length, open: open.length, review: review.length });
    const badge = document.getElementById("nav-applications-count");
    badge.textContent = confirmed.length;
    badge.hidden = !confirmed.length;
    for (const control of filters.children) {
      control.classList.toggle("active", control.dataset.filter === filter);
      control.setAttribute("aria-pressed", String(control.dataset.filter === filter));
    }
    syncButton.disabled = pending || offline || !navigator.onLine || data.sync.status === "running" || !data.sync.enabled;
    syncButton.textContent = t(pending || data.sync.status === "running" ? "Wird abgeglichen …" : "Mails abgleichen");
    addButton.disabled = offline || !navigator.onLine;
    const notes = [];
    if (offline) notes.push(t("Offline: Gespeicherte Bewerbungen. Zum Bearbeiten bitte verbinden."));
    else if (data.sync.status === "error") notes.push(t("Der Mail-Abgleich ist fehlgeschlagen. Vorhandene Bewerbungen bleiben erhalten. Bitte erneut versuchen."));
    else if (!data.sync.enabled) notes.push(t("Der automatische Mail-Abgleich ist noch nicht eingerichtet."));
    else if (data.sync.last_success_at) notes.push(t("Letzter Mail-Abgleich: {date}", { date: shortDate(data.sync.last_success_at) }));
    if (data.sync.more_history) notes.push(t("Ältere Nachrichten werden beim nächsten Abgleich weiter geprüft."));
    notice.textContent = notes.join(" ");
    const items = data.applications.filter((a) => {
      if (filter === "review" ? !review.includes(a) : !a.confirmed) return false;
      if (filter === "open" && closed.has(a.status)) return false;
      if (filter === "closed" && !closed.has(a.status)) return false;
      return !query || `${a.company} ${a.title}`.toLocaleLowerCase().includes(query);
    });
    list.replaceChildren();
    for (const app of items) {
      const job = getJobs().find((j) => j.id === app.job_id);
      const row = button("", "application-row", () => openEditor(app.id));
      row.append(companyMark(app.company, job?.company_logo_url, job?.company_logo_mode, job?.company_logo_dark_url));
      const identity = node("div", "application-identity");
      identity.append(node("span", "application-company", app.company || t("Unternehmen prüfen")),
        node("strong", "application-title", displayJobTitle(app.title) || t("Position noch nicht erkannt")));
      const context = [];
      if (job?.user_status === "saved") context.push(t("Gemerkt"));
      if (app.match_state === "review") context.push(t("Zuordnung prüfen"));
      if (!app.confirmed) context.push(t("Bewerbung bestätigen"));
      if (context.length) identity.append(node("span", "application-context", context.join(" · ")));
      const status = statusBadge(app);
      const date = node("span", "application-date");
      date.append(node("span", "", t("Letzte Nachricht")), node("time", "", shortDate(app.last_event_at)));
      const arrow = node("span", "application-arrow", "›");
      arrow.setAttribute("aria-hidden", "true");
      row.append(identity, status, date, arrow);
      list.append(row);
    }
    empty.hidden = items.length > 0;
    empty.replaceChildren(node("h2", "", t(loading ? "Bewerbungen werden geladen …" : "Hier beginnt dein nächster Schritt.")),
      node("p", "", t(filter === "review" ? "Aktuell gibt es keine Treffer zu prüfen." : "Bewerbungen aus deinen Mails erscheinen hier. Du kannst sie auch selbst erfassen.")));
  }

  async function refresh() {
    if (suspended) return;
    if (loading) return idle;
    loading = true;
    let finish;
    idle = new Promise((resolve) => { finish = resolve; });
    try {
      const fresh = await request("/api/applications");
      data = fresh;
      offline = false;
      loaded = true;
      // Only list metadata is retained offline, never message bodies or evidence excerpts.
      if (!suspended) await saveApplicationsSnapshot(data).catch(() => {});
    } catch (error) {
      if (error.authRequired) return;
      const snapshot = await readApplicationsSnapshot().catch(() => null);
      if (snapshot && !loaded) { data = snapshot; loaded = true; }
      offline = true;
    } finally { loading = false; render(); finish(); }
  }

  async function post(path, payload) {
    return request(`/api/applications/${path}`, { method: "POST", headers: {
      "Content-Type": "application/json", "X-CSRF-Token": getCsrf(),
    }, body: JSON.stringify(payload) });
  }

  async function sync() {
    if (pending) return;
    pending = true;
    render();
    try {
      await post("sync", {});
      if (suspended) { pending = false; return; }
      let polls = 0;
      clearTimeout(pollTimer);
      const poll = async () => {
        if (suspended) { pending = false; return; }
        await refresh();
        polls += 1;
        if ((data.sync.status === "running" || polls < 2) && polls < 90) pollTimer = setTimeout(poll, 2000);
        else { pending = false; render(); if (!suspended) onDataChanged(); }
      };
      pollTimer = setTimeout(poll, 1000);
    } catch (_) {
      pending = false;
      notice.textContent = t("Der Mail-Abgleich konnte nicht gestartet werden. Bitte prüfe deine Verbindung.");
      syncButton.disabled = false;
    }
  }

  async function openEditor(id = "") {
    if (dialog.open) return;
    let app = id ? data.applications.find((a) => a.id === id) : null;
    const top = node("div", "application-dialog-top");
    const title = node("h2", "", t(id ? "Bewerbung" : "Bewerbung erfassen"));
    title.id = "application-dialog-title";
    top.append(title, button("Schließen", "theme-toggle", () => dialog.close()));
    const content = node("div", "application-dialog-content");
    dialog.replaceChildren(top, content);
    dialog.showModal();
    dialog.scrollTop = 0;
    if (id && !offline) {
      content.append(node("p", "", t("Nachrichten werden geladen …")));
      try { app = (await request(`/api/applications/${id}`)).application; }
      catch (_) { content.replaceChildren(node("p", "", t("Nachrichten konnten nicht geladen werden."))); }
      if (!dialog.open) return;
    }
    content.replaceChildren();
    if (app) {
      content.append(node("p", "application-context", app.company || t("Unternehmen prüfen")),
        node("h3", "application-detail-title", displayJobTitle(app.title) || t("Position noch nicht erkannt")));
      const statusLine = node("div", "application-detail-status");
      statusLine.append(statusBadge(app));
      if (app.applied_at) statusLine.append(node("span", "application-context", t("Beworben am") + " " + shortDate(app.applied_at)));
      content.append(statusLine);
      if (!app.confirmed) content.append(node("p", "applications-notice", t("Diese Nachricht ist noch kein eindeutiger Bewerbungsnachweis. Bitte prüfen und bestätigen.")));
    }
    const form = node("form", "application-form");
    const field = (label, input) => { const wrap = node("label"); wrap.append(node("span", "", t(label)), input); form.append(wrap); return input; };
    const company = field("Unternehmen", node("input")); company.maxLength = 180; company.value = app?.company || "";
    const role = field("Position", node("input")); role.maxLength = 200; role.value = app?.title || "";
    const jobs = field("Stelle in Jobfind zuordnen", node("select"));
    const none = node("option", "", t("Keine Zuordnung")); none.value = ""; jobs.append(none);
    const suggestions = new Set((app?.candidates || []).map((c) => c.id));
    const options = [...getJobs()].sort((a, b) => Number(suggestions.has(b.id)) - Number(suggestions.has(a.id)) || a.company.localeCompare(b.company));
    for (const job of options) {
      const option = node("option", "", `${suggestions.has(job.id) ? t("Vorschlag") + ": " : ""}${job.company} · ${displayJobTitle(job.title)}${job.user_status === "saved" ? " · " + t("Gemerkt") : ""}`);
      option.value = job.id;
      jobs.append(option);
    }
    if (app?.job_id && !options.some((j) => j.id === app.job_id)) {
      const option = node("option", "", `${app.company} · ${displayJobTitle(app.title)}`); option.value = app.job_id; jobs.append(option);
    }
    jobs.value = app?.job_id || "";
    jobs.addEventListener("change", () => {
      const job = getJobs().find((j) => j.id === jobs.value);
      if (job) { company.value = job.company; role.value = job.title; }
    });
    const status = field("Stand", node("select"));
    if (app) { const auto = node("option", "", t("Automatisch aus Mails")); auto.value = ""; status.append(auto); }
    for (const value of statuses) { const option = node("option", "", applicationStatusLabel(value)); option.value = value; status.append(option); }
    status.value = app?.override_status || (app ? "" : "submitted");
    const note = field("Deine Notiz", node("textarea")); note.rows = 3; note.maxLength = 600; note.value = app?.note || "";
    let date;
    if (!app) {
      date = field("Beworben am", node("input")); date.type = "date";
      const today = new Date();
      date.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    }
    const error = node("p", "feedback-error"); error.setAttribute("role", "alert"); form.append(error);
    const buttons = node("div", "application-form-actions");
    const save = node("button", "button-primary", t(app && !app.confirmed ? "Bewerbung bestätigen" : "Speichern")); save.type = "submit";
    buttons.append(save);
    if (app) buttons.append(button("Keine Bewerbung", "button-secondary", async () => {
      if (!window.confirm(t("Diesen Eintrag aus den Bewerbungen entfernen? Deine Mails und Lesezeichen bleiben erhalten."))) return;
      await mutate({ dismissed: true });
    }));
    const job = app && getJobs().find((j) => j.id === app.job_id);
    if (job) buttons.append(button("Jobdetails", "button-secondary", () => { dialog.close(); onOpenJob(job); }));
    form.append(buttons);
    content.append(form);
    if (app?.events?.length) {
      const timeline = node("section", "application-timeline");
      timeline.append(node("h3", "", t("Verlauf aus deinen Mails")), node("p", "application-context", t("Nur eindeutige Nachrichten ändern den Stand automatisch. Unklare Nachrichten bleiben zur Prüfung sichtbar.")));
      app.events.forEach((event, index) => {
        const item = node("details", "application-event"); item.open = index === 0;
        const head = node("summary");
        head.append(node("span", "", event.source === "manual" ? t("Manuell erfasst") : event.subject), node("time", "", shortDate(event.received_at)));
        item.append(head, node("p", "application-context", `${event.sender}${event.confidence !== "high" ? " · " + t("Zu prüfen") : ""}`), node("p", "application-excerpt", event.excerpt));
        timeline.append(item);
      });
      content.append(timeline);
    } else if (offline) content.append(node("p", "applications-notice", t("Mail-Inhalte sind nur mit Internet verfügbar.")));
    for (const control of form.querySelectorAll("input, select, textarea, button")) control.disabled = offline;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!jobs.value && !company.value.trim()) { error.textContent = t("Bitte gib ein Unternehmen an oder ordne eine Stelle zu."); return; }
      const payload = { company: company.value.trim(), title: role.value.trim(), job_id: jobs.value };
      Object.assign(payload, { override_status: status.value, note: note.value });
      if (app) payload.confirmed = true;
      else if (date.value) payload.applied_at = date.value;
      await mutate(payload);
    });
    async function mutate(payload) {
      for (const control of buttons.querySelectorAll("button")) control.disabled = true;
      try {
        await post(app ? app.id : "manual", payload);
        dialog.close();
        await refresh();
        if (!suspended) onDataChanged();
      } catch (_) {
        error.textContent = t("Die Bewerbung konnte nicht gespeichert werden. Bitte versuche es erneut.");
        for (const control of buttons.querySelectorAll("button")) control.disabled = false;
      }
    }
  }

  render();
  return {
    show(value) { panel.hidden = !value; visible = value; if (value && !loaded) refresh(); },
    refresh,
    async suspend() { suspended = true; clearTimeout(pollTimer); await idle; },
    resume() { suspended = false; pending = false; },
    isOpen: () => dialog.open,
  };
}
