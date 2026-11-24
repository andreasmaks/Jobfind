import { request } from "/assets/api.js?v=23";
import { readApplicationsSnapshot, saveApplicationsSnapshot } from "/assets/offline.js?v=32";
import { companyMark, displayJobTitle, shortDate, applicationStatusLabel } from "/assets/ui.js?v=9";

const { t, locale } = window.JobfindI18n;
const reviewReasons = {
  portal_required: "Bewerbungsportal: weiterer Schritt erforderlich",
  listing_unverified: "Anzeige derzeit nicht sicher prüfbar",
  listing_expired: "Anzeige abgelaufen",
  route_unverified: "Bewerbungsadresse muss erneut geprüft werden",
  delivery_unknown: "Versandantwort unklar · kein erneuter Versand",
  delivery_failed: "Nicht zugestellt · manueller Schritt erforderlich",
  mail_connection_failed: "Mail-Verbindung fehlgeschlagen",
  sender_rejected: "Absender wurde nicht akzeptiert",
  recipient_rejected: "Empfänger wurde nicht akzeptiert",
};
const statuses = ["submitted", "reviewing", "interview", "offer", "rejected", "withdrawn", "delivery_failed"];
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
const icon = (paths) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "lucide-icon");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
};
const iconButton = (label, paths, action) => {
  const control = button(label, "export-button", action);
  control.replaceChildren(icon(paths));
  control.setAttribute("aria-label", t(label));
  control.title = t(label);
  return control;
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
  const heading = node("h1", "visually-hidden", t("Bewerbungen"));
  const header = node("div", "search-section applications-header");
  const searchLine = node("div", "search-line");
  const count = node("span", "header-job-count applications-count");
  count.setAttribute("aria-live", "polite");
  const countValue = node("span");
  const countLabel = node("span", "applications-count-label");
  count.append(countValue, countLabel);
  const syncButton = iconButton("Mails abgleichen", ["M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", "M8 16H3v5"], sync);
  syncButton.className = "applications-sync";
  const syncCopy = node("span", "applications-sync-copy");
  const syncLabel = node("span", "applications-sync-label");
  const syncDate = node("span", "applications-sync-date");
  syncCopy.append(syncLabel, syncDate);
  syncButton.append(syncCopy);
  const overview = node("div", "applications-overview");
  overview.append(count, syncButton);
  const filters = node("div", "applications-filters");
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", t("Bewerbungen filtern"));
  for (const [key, label] of [["all", "Alle"], ["received", "Eingegangen"], ["invited", "Eingeladen"], ["rejected", "Absage"]]) {
    const control = button(label, "", () => { filter = key; render(); });
    control.dataset.filter = key;
    filters.append(control);
  }
  const searchLabel = node("label", "search-field");
  searchLabel.append(node("span", "visually-hidden", t("Bewerbungen durchsuchen")));
  const search = node("input");
  search.type = "search";
  search.autocomplete = "off";
  search.placeholder = t("Unternehmen oder Position suchen");
  search.addEventListener("input", () => { query = search.value.trim().toLocaleLowerCase(); render(); });
  searchLabel.append(search, icon(["m21 21-4.34-4.34", "M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0"]));
  const tools = node("div", "applications-tools");
  tools.append(searchLabel);
  searchLine.append(overview, filters, tools);
  const notice = node("p", "applications-notice");
  notice.setAttribute("role", "status");
  const list = node("div", "applications-list");
  const empty = node("div", "empty-state applications-empty");
  header.append(searchLine, notice);
  panel.append(heading, header, list, empty);
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
    const items = data.applications.filter((a) => {
      // Keep uncertain mail matches accessible under All without promoting them.
      if (filter !== "all" && !a.confirmed) return false;
      if (filter === "received" && !["submitted", "reviewing"].includes(a.status)) return false;
      if (filter === "invited" && a.status !== "interview") return false;
      if (filter === "rejected" && a.status !== "rejected") return false;
      return !query || `${a.company} ${a.title}`.toLocaleLowerCase().includes(query);
    });
    countValue.textContent = items.length;
    countLabel.textContent = t(items.length === 1 ? "Bewerbung" : "Bewerbungen");
    count.setAttribute("aria-label", `${items.length} ${countLabel.textContent}`);
    const badge = document.getElementById("nav-applications-count");
    badge.textContent = confirmed.length;
    badge.hidden = !confirmed.length;
    for (const control of filters.children) {
      control.classList.toggle("active", control.dataset.filter === filter);
      control.setAttribute("aria-pressed", String(control.dataset.filter === filter));
    }
    syncButton.disabled = pending || offline || !navigator.onLine || data.sync.status === "running" || !data.sync.enabled;
    const syncing = pending || data.sync.status === "running";
    const lastSync = data.sync.last_success_at ? new Date(data.sync.last_success_at) : null;
    const lastSyncText = lastSync && !Number.isNaN(lastSync.getTime())
      ? new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(lastSync)
      : t("Noch kein Abgleich");
    syncLabel.textContent = t(syncing ? "Wird abgeglichen …" : "Letzter Abgleich");
    syncDate.textContent = lastSyncText;
    const syncDescription = t(syncing ? "Wird abgeglichen …" : "Mails abgleichen") + ". " + t("Letzter Abgleich") + ": " + lastSyncText;
    syncButton.setAttribute("aria-label", syncDescription);
    syncButton.setAttribute("aria-busy", String(syncing));
    syncButton.title = syncDescription;
    const notes = [];
    if (offline) notes.push(t("Offline: Gespeicherte Bewerbungen. Zum Bearbeiten bitte verbinden."));
    else if (data.sync.status === "error") notes.push(t("Der Mail-Abgleich ist fehlgeschlagen. Vorhandene Bewerbungen bleiben erhalten. Bitte erneut versuchen."));
    else if (!data.sync.enabled) notes.push(t("Der automatische Mail-Abgleich ist noch nicht eingerichtet."));
    if (data.sync.more_history) notes.push(t("Ältere Nachrichten werden beim nächsten Abgleich weiter geprüft."));
    notice.textContent = notes.join(" ");
    const intents = data.automation?.items || [];
    const linked = new Set(data.applications.flatMap((app) => [app.job_id, ...(app.candidates || []).map((job) => job.id)]).filter(Boolean));
    const pendingApplications = offline || filter !== "all" ? [] : intents.filter((item) => item.state !== "sent" && !linked.has(item.job_id)
      && (!query || `${item.company} ${item.title}`.toLocaleLowerCase().includes(query)));
    list.replaceChildren();
    for (const app of items) {
      const job = getJobs().find((j) => j.id === app.job_id);
      const open = () => openEditor(app.id);
      const row = node("article", "application-row");
      row.addEventListener("click", (event) => { if (!event?.target?.closest("button, a")) return open(); });
      row.append(companyMark(app.company, job?.company_logo_url, job?.company_logo_mode, job?.company_logo_dark_url));
      const identity = node("div", "application-identity");
      const titleButton = button("", "application-title application-title-button", open);
      titleButton.textContent = displayJobTitle(app.title) || t("Position noch nicht erkannt");
      identity.append(node("span", "application-company", app.company || t("Unternehmen prüfen")),
        titleButton);
      const context = [];
      if (job?.user_status === "saved") context.push(t("Gemerkt"));
      if (app.match_state === "review") context.push(t("Zuordnung prüfen"));
      if (!app.confirmed) context.push(t("Bewerbung bestätigen"));
      if (context.length) identity.append(node("span", "application-context", context.join(" · ")));
      const status = statusBadge(app);
      const date = node("span", "application-date");
      date.append(node("span", "", t("Letzte Nachricht")), node("time", "", shortDate(app.last_event_at)));
      const needsReview = !app.confirmed || app.match_state === "review" || app.status === "delivery_failed"
        || intents.some((item) => item.job_id === app.job_id && item.state !== "sent");
      const action = needsReview ? button("Prüfen", "application-review-button", open)
        : iconButton("Details", ["m9 18 6-6-6-6"], open);
      if (!needsReview) action.className = "application-open-button";
      row.append(identity, status, date, action);
      list.append(row);
    }
    for (const item of pendingApplications) {
      const job = getJobs().find((candidate) => candidate.id === item.job_id);
      const open = () => openReview(item);
      const row = node("article", "application-row application-pending-row");
      row.addEventListener("click", (event) => { if (!event?.target?.closest("button, a")) return open(); });
      const identity = node("div", "application-identity");
      const titleButton = button("", "application-title application-title-button", open);
      titleButton.textContent = displayJobTitle(item.title);
      identity.append(node("span", "application-company", item.company), titleButton,
        node("span", "application-context", t("Übermittlung noch nicht bestätigt")));
      row.append(companyMark(item.company, job?.company_logo_url, job?.company_logo_mode, job?.company_logo_dark_url), identity,
        statusBadge({ confirmed: false }), node("span", "application-date", shortDate(item.checked_at)), button("Prüfen", "application-review-button", open));
      list.append(row);
    }
    empty.hidden = items.length + pendingApplications.length > 0;
    empty.replaceChildren(node("h2", "", t(loading ? "Bewerbungen werden geladen …" : "Hier beginnt dein nächster Schritt.")),
      node("p", "", t(filter === "all" ? "Bewerbungen zu deinen Jobfind-Stellen erscheinen hier." : "Für diese Auswahl gibt es noch keine Bewerbungen.")));
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
      render();
      notice.textContent = t("Der Mail-Abgleich konnte nicht gestartet werden. Bitte prüfe deine Verbindung.");
    }
  }

  function openShell(titleText) {
    if (dialog.open) return null;
    const top = node("div", "application-dialog-top");
    const title = node("h2", "", titleText);
    title.id = "application-dialog-title";
    title.tabIndex = -1;
    title.setAttribute("autofocus", "");
    const close = iconButton("Schließen", ["M18 6 6 18", "m6 6 12 12"], () => dialog.close());
    close.className = "dialog-close";
    top.append(title, close);
    const content = node("div", "application-dialog-content");
    dialog.replaceChildren(top, content);
    dialog.showModal();
    dialog.scrollTop = 0;
    return { title, content };
  }

  function openReview(item) {
    const shell = openShell(displayJobTitle(item.title) || t("Position noch nicht erkannt"));
    if (!shell) return;
    const job = getJobs().find((candidate) => candidate.id === item.job_id);
    shell.content.append(node("p", "application-context", item.company),
      node("p", "applications-notice", t(reviewReasons[item.reason] || "Bewerbungsportal: weiterer Schritt erforderlich")),
      node("p", "application-context", t("Übermittlung noch nicht bestätigt")));
    if (job) {
      const actions = node("div", "application-form-actions");
      const link = node("a", "card-cta", t("Anzeige öffnen"));
      link.href = job.original_url; link.target = "_blank"; link.rel = "noopener noreferrer";
      actions.append(link, button("Jobdetails", "button-secondary", () => { dialog.close(); onOpenJob(job); }));
      shell.content.append(actions);
    }
  }

  async function openEditor(id = "") {
    let app = id ? data.applications.find((a) => a.id === id) : null;
    const shell = openShell(displayJobTitle(app?.title) || t(id ? "Bewerbung" : "Bewerbung erfassen"));
    if (!shell) return;
    const { title, content } = shell;
    if (id && !offline) {
      content.append(node("p", "", t("Nachrichten werden geladen …")));
      try { app = (await request(`/api/applications/${id}`)).application; }
      catch (_) { content.replaceChildren(node("p", "", t("Nachrichten konnten nicht geladen werden."))); }
      if (!dialog.open) return;
    }
    content.replaceChildren();
    if (app) {
      title.textContent = displayJobTitle(app.title) || t("Position noch nicht erkannt");
      content.append(node("p", "application-context", app.company || t("Unternehmen prüfen")));
      const statusLine = node("div", "application-detail-status");
      statusLine.append(statusBadge(app));
      if (app.applied_at) statusLine.append(node("span", "application-context", t("Beworben am") + " " + shortDate(app.applied_at)));
      content.append(statusLine);
      if (!app.confirmed) content.append(node("p", "applications-notice", t("Diese Nachricht ist noch kein eindeutiger Bewerbungsnachweis. Bitte prüfen und bestätigen.")));
    }
    const form = node("form", "application-form");
    const field = (label, input, className = "") => { const wrap = node("label", className); wrap.append(node("span", "", t(label)), input); form.append(wrap); return input; };
    const company = field("Unternehmen", node("input")); company.maxLength = 180; company.value = app?.company || "";
    const role = field("Position", node("input")); role.maxLength = 200; role.value = app?.title || "";
    const jobs = field("Stelle in Jobfind zuordnen", node("select"));
    const none = node("option", "", t("Keine Zuordnung")); none.value = ""; jobs.append(none);
    const suggestions = new Set((app?.candidates || []).map((c) => c.id));
    const options = [...getJobs()].sort((a, b) => Number(suggestions.has(b.id)) - Number(suggestions.has(a.id)) || a.company.localeCompare(b.company));
    for (const job of options) {
      const assigned = job.id === app?.job_id;
      const option = node("option", "", `${!assigned && suggestions.has(job.id) ? t("Vorschlag") + ": " : ""}${job.company} · ${displayJobTitle(job.title)}${!assigned && job.user_status === "saved" ? " · " + t("Gemerkt") : ""}`);
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
    close() { if (dialog.open) dialog.close(); },
  };
}
