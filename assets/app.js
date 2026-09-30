import { changeDeletion, loadPortal, updateLike, updateStatus } from "/assets/api.js?v=5";
import { clearOfflineData, prepareOffline, readPendingActions, removePendingAction, savePendingAction } from "/assets/offline.js?v=5";
import { createCard, shortDate, showDetails } from "/assets/ui.js?v=2";

const { t, locale, translatePage } = window.JobfindI18n;
translatePage();

const state = { jobs: [], meta: null, csrf: "", tab: "all", offline: false, savedAt: "", offlineReady: false, pendingActions: [], syncError: "" };
let portalLoaded = false;
let mutationPending = false;
let mutationVersion = 0;
let offlinePreparation = Promise.resolve();
let syncInFlight = false;
const deletedJobs = [];
const $ = (id) => document.getElementById(id);
const grid = $("jobs-grid");
const dialog = $("job-dialog");
const feedbackDialog = $("feedback-dialog");
let feedbackJob = null;
const controls = ["search", "remote-filter", "hours-filter", "score-filter", "sort-filter", "visibility-filter"];

function setupHeaderInfoMenu() {
  const actions = $("header-actions");
  const toggle = $("header-info-toggle");
  const mobile = window.matchMedia("(max-width: 650px)");
  const close = (restoreFocus = false) => {
    actions.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    if (restoreFocus) toggle.focus();
  };
  toggle.addEventListener("click", () => {
    const open = actions.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", (event) => {
    if (!actions.contains(event.target)) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && actions.classList.contains("is-open")) {
      event.preventDefault();
      close(true);
    }
  });
  actions.addEventListener("focusout", (event) => {
    if (event.relatedTarget && !actions.contains(event.relatedTarget)) close();
  });
  mobile.addEventListener("change", () => {
    if (!mobile.matches) close();
  });
}

function setupFilterPanel() {
  const panel = $("filter-panel");
  const trigger = panel.querySelector("summary");
  document.addEventListener("click", (event) => {
    if (panel.open && !panel.contains(event.target)) panel.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && panel.open) {
      event.preventDefault();
      panel.open = false;
      trigger.focus();
    }
  });
  panel.addEventListener("focusout", (event) => {
    if (event.relatedTarget && !panel.contains(event.relatedTarget)) panel.open = false;
  });
}

function filteredJobs() {
  const search = $("search").value.trim().toLocaleLowerCase("de-DE");
  const remote = $("remote-filter").value;
  const hours = $("hours-filter").value;
  const minScore = Number($("score-filter").value);
  const hidden = $("visibility-filter").value === "hidden";
  const items = state.jobs.filter((job) => {
    if ((job.user_status === "hidden") !== hidden) return false;
    if (state.tab === "saved" && job.user_status !== "saved") return false;
    if (state.tab === "history" && !job.historical) return false;
    const haystack = [job.title, job.company, job.location, job.remote].join(" ").toLocaleLowerCase("de-DE");
    if (search && !haystack.includes(search)) return false;
    const work = [job.remote, job.location].join(" ").toLocaleLowerCase("de-DE");
    if (remote === "remote" && !/remote|homeoffice|home office|mobiles arbeiten|ortsunabhängig/.test(work)) return false;
    if (remote === "hybrid" && !/hybrid|bürotag|präsenztag/.test(work)) return false;
    const workHours = String(job.hours || "").toLocaleLowerCase("de-DE");
    if (hours === "parttime" && !job.part_time_hint && !/teilzeit|part.?time/.test(workHours)) return false;
    if (hours === "fulltime" && !/vollzeit|40\s*(stunden|std)/.test(workHours)) return false;
    if (minScore && Number(job.score || 0) < minScore) return false;
    return true;
  });
  const sort = $("sort-filter").value;
  items.sort((a, b) => {
    if (sort === "score") return (b.score || 0) - (a.score || 0) || b.first_seen_at.localeCompare(a.first_seen_at);
    if (sort === "company") return a.company.localeCompare(b.company, locale);
    return b.first_seen_at.localeCompare(a.first_seen_at);
  });
  return items;
}

function updateRunNote() {
  const run = state.meta?.last_run;
  const note = $("run-note");
  note.hidden = run?.status !== "error";
  note.textContent = run?.status === "error"
    ? t("Der letzte Suchlauf hatte einen Fehler. Frühere Treffer bleiben sichtbar.")
    : "";
}

function updateOfflineState() {
  const note = $("offline-state");
  const pending = state.pendingActions.length;
  note.hidden = !pending && !syncInFlight && !state.syncError;
  note.classList.toggle("is-offline", state.offline);
  if (state.offline && pending) {
    note.textContent = t(pending === 1 ? "{count} Änderung lokal gespeichert. Wird beim Verbinden übertragen." : "{count} Änderungen lokal gespeichert. Wird beim Verbinden übertragen.", { count: pending });
  } else if (syncInFlight) {
    note.textContent = t(pending === 1 ? "{count} Offline-Änderung wird übertragen …" : "{count} Offline-Änderungen wird übertragen …", { count: pending });
  } else if (state.syncError) {
    note.textContent = `${pending ? t(pending === 1 ? "{count} Änderung noch nicht übertragen." : "{count} Änderungen noch nicht übertragen.", { count: pending }) + " " : ""}${state.syncError}`;
  } else if (pending) {
    note.textContent = t(pending === 1 ? "{count} Änderung wartet auf Übertragung." : "{count} Änderungen wartet auf Übertragung.", { count: pending });
  } else {
    note.textContent = "";
  }
  document.body.classList.toggle("is-offline", state.offline);
  $("undo-delete").disabled = mutationPending || syncInFlight;
}

function queueOfflineCopy() {
  if (state.pendingActions.length) return;
  const jobs = state.jobs.map((job) => ({ ...job }));
  const meta = state.meta;
  offlinePreparation = offlinePreparation.catch(() => {}).then(() => prepareOffline(jobs, meta))
    .then((savedAt) => {
      state.savedAt = savedAt;
      state.offlineReady = true;
      updateOfflineState();
    })
    .catch(() => {
      state.offlineReady = false;
      if (!state.offline) {
        const note = $("offline-state");
        note.hidden = false;
        note.textContent = t("Offline-Kopie konnte nicht gespeichert werden. Bitte lade die Seite mit Internet erneut.");
      }
    });
}

function applyPendingActions(jobs, actions) {
  const byId = new Map(jobs.map((job) => [job.id, { ...job }]));
  for (const action of actions) {
    if (action.kind === "delete") byId.delete(action.jobId);
    else if (action.kind === "restore") byId.set(action.jobId, { ...action.job });
    else if (action.kind === "status" && byId.has(action.jobId)) byId.get(action.jobId).user_status = action.status;
    else if (action.kind === "like" && byId.has(action.jobId)) byId.get(action.jobId).liked = action.liked;
  }
  return [...byId.values()];
}

async function queueAction(action, offlineMode) {
  const jobs = state.jobs.map((job) => ({ ...job }));
  const meta = state.meta;
  offlinePreparation = offlinePreparation.catch(() => {}).then(() => savePendingAction(action, jobs, meta));
  const saved = await offlinePreparation;
  state.pendingActions.push({ ...action, id: saved.id });
  state.savedAt = saved.savedAt;
  state.offlineReady = true;
  state.offline = offlineMode;
  if (offlineMode) state.csrf = "";
  state.syncError = "";
  updateOfflineState();
}

async function sendAction(action) {
  if (action.kind === "status") return updateStatus(action.jobId, action.status, state.csrf);
  if (action.kind === "like") return updateLike(action.jobId, action.liked, state.csrf);
  return changeDeletion(action.jobId, action.kind === "delete", state.csrf, action.feedback || {});
}

async function saveAction(action) {
  let offlineMode = state.offline || !navigator.onLine;
  if (!offlineMode && !state.pendingActions.length) {
    try {
      await sendAction(action);
      queueOfflineCopy();
      return;
    } catch (error) {
      if (!error.networkFailure) throw error;
      offlineMode = true;
    }
  }
  await queueAction(action, offlineMode);
}

async function syncPendingActions() {
  if (syncInFlight || state.offline || !state.pendingActions.length || mutationPending) return !state.pendingActions.length;
  syncInFlight = true;
  state.syncError = "";
  render();
  try {
    let unavailable = 0;
    for (const action of [...state.pendingActions]) {
      try {
        await sendAction(action);
      } catch (error) {
        if (error.httpStatus !== 404) throw error;
        unavailable += 1;
      }
      await removePendingAction(action.id);
      state.pendingActions.shift();
      updateOfflineState();
    }
    if (unavailable) state.syncError = t(unavailable === 1 ? "{count} Änderung entfiel, weil die Stelle nicht mehr verfügbar ist." : "{count} Änderungen entfielen, weil die Stelle nicht mehr verfügbar ist.", { count: unavailable });
    const loaded = await loadPortal();
    state.offline = loaded.offline;
    state.csrf = loaded.csrf;
    state.jobs = loaded.jobs;
    state.meta = loaded.meta;
    if (!loaded.offline) queueOfflineCopy();
    return !loaded.offline;
  } catch (error) {
    if (error.networkFailure) {
      state.offline = true;
      state.csrf = "";
    }
    state.syncError = t("Bitte später erneut verbinden; deine Änderungen bleiben auf diesem Gerät gespeichert.");
    return false;
  } finally {
    syncInFlight = false;
    render();
  }
}

function updateSummary(jobs = filteredJobs()) {
  const total = jobs.length;
  const saved = state.jobs.filter((job) => job.user_status === "saved").length;
  const updated = shortDate(state.meta?.last_success_at);
  $("header-job-count").textContent = t(total === 1 ? "{count} Job" : "{count} Jobs", { count: total });
  $("header-job-count").setAttribute("aria-label", t(total === 1 ? "{count} Job in dieser Auswahl" : "{count} Jobs in dieser Auswahl", { count: total }));
  $("header-updated").textContent = updated ? t("Stand: {date}", { date: updated }) : "";
  $("header-updated").hidden = !updated;
  $("nav-saved-count").textContent = saved;
  $("nav-saved-count").hidden = saved === 0;
}

function render() {
  const jobs = filteredJobs();
  const fragment = document.createDocumentFragment();
  jobs.forEach((job) => fragment.append(createCard(job, openJob, changeStatus, askDelete, changeLike)));
  grid.replaceChildren(fragment);
  $("empty-state").hidden = jobs.length > 0;
  $("empty-copy").textContent = state.jobs.length
    ? t("Für diese Auswahl gibt es noch keine Stellen. Passe die Suche oder Filter an.")
    : t("Sobald Hermes passende Stellen findet, erscheinen sie hier.");
  $("filter-badge").hidden = !($("remote-filter").value !== "all" || $("hours-filter").value !== "all" || $("score-filter").value !== "0" || $("visibility-filter").value !== "visible");
  updateSummary(jobs);
  updateRunNote();
  updateOfflineState();
  grid.querySelectorAll(".card-actions button").forEach((button) => { button.disabled = mutationPending || syncInFlight; });
  grid.querySelectorAll('a[target="_blank"]').forEach((link) => {
    link.setAttribute("aria-disabled", String(state.offline));
    link.tabIndex = state.offline ? -1 : 0;
  });
}

function openJob(job) {
  showDetails(dialog, job, changeStatus);
  dialog.querySelectorAll("#dialog-save, .dialog-actions button").forEach((button) => {
    button.disabled = syncInFlight;
  });
  dialog.querySelectorAll('a[target="_blank"]').forEach((link) => {
    link.setAttribute("aria-disabled", String(state.offline));
    link.tabIndex = state.offline ? -1 : 0;
  });
}

async function changeStatus(job, status) {
  if (mutationPending || syncInFlight) return;
  mutationPending = true;
  mutationVersion += 1;
  const previous = job.user_status;
  job.user_status = status;
  render();
  if (dialog.open) {
    dialog.close();
    if (status !== "hidden") openJob(job);
  }
  try {
    await saveAction({ kind: "status", jobId: job.id, status });
  } catch (error) {
    job.user_status = previous;
    render();
    window.alert(t("Die Änderung konnte nicht gespeichert werden. Bitte versuche es erneut."));
  } finally {
    mutationPending = false;
    render();
    if (!state.offline && state.pendingActions.length) syncPendingActions();
  }
}

function deletionNotice() {
  $("deletion-notice").hidden = deletedJobs.length === 0;
  const last = deletedJobs.at(-1);
  $("deletion-message").textContent = last
    ? t("„{title}“ gelöscht. {detail}", { title: last.title, detail: t(state.pendingActions.some((action) => action.kind === "delete" && action.jobId === last.id) ? "Wird nach dem Verbinden übertragen." : "Hermes berücksichtigt das bei künftigen Empfehlungen.") })
    : "";
  $("undo-delete").disabled = mutationPending || syncInFlight;
}

function askDelete(job) {
  if (mutationPending || syncInFlight) return;
  feedbackJob = job;
  $("feedback-form").reset();
  $("feedback-error").hidden = true;
  $("feedback-job").textContent = `${job.title} · ${job.company}`;
  feedbackDialog.showModal();
}

$("feedback-cancel").addEventListener("click", () => feedbackDialog.close());
feedbackDialog.addEventListener("cancel", (event) => {
  if (mutationPending) event.preventDefault();
});
$("feedback-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!feedbackJob || mutationPending) return;
  const values = new FormData(event.currentTarget);
  removeJob(feedbackJob, { reasons: values.getAll("reason"), note: values.get("note") });
});

async function changeLike(job) {
  if (mutationPending || syncInFlight) return;
  mutationPending = true;
  mutationVersion += 1;
  const previous = Boolean(job.liked);
  const hadFocus = grid.querySelector(`[data-job-id="${job.id}"] .like-button`) === document.activeElement;
  job.liked = !previous;
  render();
  try {
    await saveAction({ kind: "like", jobId: job.id, liked: job.liked });
  } catch (error) {
    job.liked = previous;
    window.alert(t("Dein Gefällt mir konnte nicht gespeichert werden. Bitte versuche es erneut."));
  } finally {
    mutationPending = false;
    render();
    if (!state.offline && state.pendingActions.length) syncPendingActions();
    if (hadFocus) grid.querySelector(`[data-job-id="${job.id}"] .like-button`)?.focus();
  }
}

async function removeJob(job, feedback) {
  if (mutationPending || syncInFlight) return;
  mutationPending = true;
  mutationVersion += 1;
  const cards = [...grid.children];
  const index = cards.findIndex((card) => card.dataset.jobId === job.id);
  $("feedback-error").hidden = true;
  $("feedback-form").querySelectorAll("button,input,textarea").forEach((input) => { input.disabled = true; });
  $("feedback-submit").textContent = t("Wird gespeichert …");
  grid.querySelectorAll(".card-actions button").forEach((button) => { button.disabled = true; });
  deletionNotice();
  let removed = false;
  const previousJobs = state.jobs;
  state.jobs = state.jobs.filter((item) => item.id !== job.id);
  try {
    await saveAction({ kind: "delete", jobId: job.id, job: { ...job }, feedback });
    deletedJobs.push(job);
    removed = true;
    feedbackDialog.close();
  } catch (error) {
    state.jobs = previousJobs;
    $("feedback-error").textContent = t("Das Feedback konnte nicht gespeichert werden. Bitte versuche es erneut.");
    $("feedback-error").hidden = false;
  } finally {
    mutationPending = false;
    $("feedback-form").querySelectorAll("button,input,textarea").forEach((input) => { input.disabled = false; });
    $("feedback-submit").textContent = t("Löschen & Feedback speichern");
    render();
    deletionNotice();
    if (!state.offline && state.pendingActions.length) syncPendingActions();
    if (removed) {
      const next = grid.children[Math.max(0, Math.min(index, grid.children.length - 1))];
      (next?.querySelector(".delete-button") || $("undo-delete")).focus();
    }
  }
}

$("undo-delete").addEventListener("click", async () => {
  if (mutationPending || syncInFlight || !deletedJobs.length) return;
  const job = deletedJobs.at(-1);
  mutationPending = true;
  mutationVersion += 1;
  deletionNotice();
  const wasVisible = state.jobs.some((item) => item.id === job.id);
  if (!wasVisible) state.jobs.push(job);
  try {
    await saveAction({ kind: "restore", jobId: job.id, job: { ...job } });
    deletedJobs.pop();
  } catch (error) {
    if (!wasVisible) state.jobs = state.jobs.filter((item) => item.id !== job.id);
    window.alert(t("Die Stelle konnte nicht wiederhergestellt werden. Bitte versuche es erneut."));
  } finally {
    mutationPending = false;
    render();
    deletionNotice();
    if (!state.offline && state.pendingActions.length) syncPendingActions();
    if (!deletedJobs.length) {
      (grid.querySelector(`[data-job-id="${job.id}"] .delete-button`) || $("search")).focus();
    }
  }
});

setupHeaderInfoMenu();
setupFilterPanel();

document.querySelectorAll(".top-nav [data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    state.tab = button.dataset.tab;
    $("visibility-filter").value = "visible";
    document.querySelectorAll(".top-nav [data-tab]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    render();
  });
});
controls.forEach((id) => $(id).addEventListener(id === "search" ? "input" : "change", render));
dialog.addEventListener("click", (event) => {
  if (event.target !== dialog) return;
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) {
    dialog.close();
  }
});

document.addEventListener("click", (event) => {
  if (state.offline && event.target.closest('a[target="_blank"]')) event.preventDefault();
}, true);

document.querySelector(".header-actions form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.offline) {
    window.alert(t("Zum Abmelden bitte erst wieder mit dem Internet verbinden."));
    return;
  }
  try {
    state.pendingActions = await readPendingActions();
    if (state.pendingActions.length && !await syncPendingActions()) {
      window.alert(t("Offline-Änderungen konnten noch nicht übertragen werden. Bitte später erneut abmelden."));
      return;
    }
    await offlinePreparation;
    await clearOfflineData();
    const response = await fetch("/logout", {
      method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": state.csrf },
    });
    if (!response.ok) throw new Error("Logout failed");
    window.location.href = "/login";
  } catch (_) {
    window.alert(t("Die Offline-Kopie konnte nicht entfernt werden. Bitte versuche es erneut."));
  }
});

try {
  state.pendingActions = await readPendingActions();
  const loaded = await loadPortal();
  state.jobs = applyPendingActions(loaded.jobs, state.pendingActions);
  state.meta = loaded.meta;
  state.csrf = loaded.csrf;
  state.offline = loaded.offline;
  state.savedAt = loaded.savedAt || "";
  state.offlineReady = loaded.offline;
  portalLoaded = true;
  render();
  if (!loaded.offline) {
    if (state.pendingActions.length) syncPendingActions();
    else queueOfflineCopy();
  }
} catch (error) {
  $("run-note").textContent = t("Die Stellen konnten nicht geladen werden. Bitte lade die Seite erneut.");
  $("run-note").hidden = false;
  $("empty-state").hidden = false;
  $("empty-copy").textContent = t("Bitte versuche es gleich noch einmal.");
}

let refreshInFlight = false;
async function refreshPortal() {
  if (refreshInFlight || syncInFlight || mutationPending || document.hidden || dialog.open || feedbackDialog.open) return;
  refreshInFlight = true;
  const version = mutationVersion;
  try {
    const loaded = await loadPortal();
    if (mutationPending || feedbackDialog.open || version !== mutationVersion) return;
    const mergedJobs = applyPendingActions(loaded.jobs, state.pendingActions);
    const jobsChanged = !portalLoaded || JSON.stringify(mergedJobs) !== JSON.stringify(state.jobs);
    const modeChanged = state.offline !== loaded.offline;
    state.jobs = mergedJobs;
    state.meta = loaded.meta;
    state.csrf = loaded.csrf;
    state.offline = loaded.offline;
    if (loaded.offline) state.savedAt = loaded.savedAt;
    portalLoaded = true;
    if (jobsChanged || modeChanged) render();
    else {
      updateSummary();
      updateRunNote();
    }
    if (!loaded.offline) {
      if (state.pendingActions.length) syncPendingActions();
      else queueOfflineCopy();
    }
  } catch (error) {
    // Keep already loaded jobs visible if a background refresh fails.
  } finally {
    refreshInFlight = false;
  }
}

window.setInterval(refreshPortal, 5 * 60 * 1000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshPortal();
});
window.addEventListener("offline", () => {
  if (!portalLoaded) return;
  state.offline = true;
  state.csrf = "";
  render();
});
window.addEventListener("online", refreshPortal);
