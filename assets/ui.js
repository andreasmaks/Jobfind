// Lucide icons v1.47.0, ISC license: https://lucide.dev/license
const icon = (paths) => `<svg class="lucide-icon" viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
const bookmark = icon('<path d="M17 3a2 2 0 0 1 2 2v15a1 1 0 0 1-1.496.868l-4.512-2.578a2 2 0 0 0-1.984 0l-4.512 2.578A1 1 0 0 1 5 20V5a2 2 0 0 1 2-2z"/>');
const trash = icon('<path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/>');
const heart = icon('<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>');
const building = icon('<path d="M10 12h4M10 8h4"/><path d="M14 21v-3a2 2 0 0 0-4 0v3"/><path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2"/><path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/>');
const sparkles = icon('<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><path d="M20 2v4M22 4h-4"/><circle cx="4" cy="20" r="2"/>');
const externalLink = icon('<path d="M15 3h6v6M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>');
function companyMark() {
  const mark = element("div", "company-mark is-fallback");
  mark.setAttribute("aria-hidden", "true");
  mark.innerHTML = building; // Constant licensed icon, never imported text.
  return mark;
}

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = String(content);
  return node;
}

export function displayJobTitle(value) {
  return String(value || "")
    .replace(/\s*[\[(]\s*(?:(?:m|w|f|d|x|div|gn)\s*[/,|]\s*){1,4}(?:m|w|f|d|x|div|gn)\s*[\])]/gi, "")
    .replace(/\s*[\[(]\s*(?:all genders|alle geschlechter|geschlechtsneutral|gn)\s*[\])]/gi, "")
    .replace(/([A-Za-zÄÖÜäöüß]+)(?::in|\*in|\/-?in)\b/gi, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function shortDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function relativeDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const current = new Date();
  const today = new Date(current.getFullYear(), current.getMonth(), current.getDate());
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const difference = Math.round((today - day) / 86400000);
  if (difference === 0) return "Heute";
  if (difference === 1) return "Gestern";
  return shortDate(value);
}

function hoursLabel(value) {
  const hours = String(value || "");
  const range = hours.match(/(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(?:Stunden|Std)/i);
  if (range) return `${range[1]}–${range[2]} Std.`;
  const minimum = hours.match(/(?:ab|mindestens)\s*(\d{1,2})\s*(?:Stunden|Std)/i);
  if (minimum) return `ab ${minimum[1]} Std.`;
  const exact = hours.match(/(\d{1,2})\s*(?:Stunden|Std)(?:\/Woche)?/i);
  if (exact) return `${exact[1]} Std.`;
  const percentage = hours.match(/\b(\d{2})\s*%/);
  if (percentage) return `${percentage[1]} %`;
  if (/teilzeit/i.test(hours)) return "Teilzeit möglich";
  if (/vollzeit/i.test(hours)) return "Vollzeit";
  return "Stunden offen";
}

function remoteLabel(job) {
  const value = `${job.remote || ""} ${job.location || ""}`.toLocaleLowerCase("de-DE");
  if (/hybrid|bürotag|präsenztag/.test(value)) return "Hybrid";
  if (/remote|homeoffice|home office|mobiles arbeiten|ortsunabhängig/.test(value)) return "Remote möglich";
  return "Arbeitsmodell offen";
}

function shortLocation(value) {
  return String(value || "Ort nicht angegeben").split(";")[0].trim().slice(0, 70);
}

function chip(value, className = "") {
  return element("span", `chip ${className}`.trim(), value);
}

export function createCard(job, onOpen, onSave, onDelete, onLike) {
  const card = element("article", "job-card");
  card.dataset.jobId = job.id;
  card.addEventListener("click", (event) => {
    if (!event.target.closest("a, button")) onOpen(job);
  });
  const top = element("div", "card-top");
  const company = String(job.company || "?").trim();
  const mark = companyMark(company, job.company_logo_url, job.company_logo_mode);
  const identity = element("div", "company-identity");
  identity.append(element("p", "company-name", job.company), element("p", "company-location", shortLocation(job.location)));
  const save = element("button", `save-button${job.user_status === "saved" ? " is-saved" : ""}`);
  save.type = "button";
  save.innerHTML = bookmark;
  save.setAttribute("aria-label", job.user_status === "saved" ? "Aus Merkliste entfernen" : "Stelle merken");
  save.title = save.getAttribute("aria-label");
  save.addEventListener("click", () => onSave(job, job.user_status === "saved" ? "new" : "saved"));
  const remove = element("button", "save-button delete-button");
  remove.type = "button";
  remove.innerHTML = trash;
  remove.setAttribute("aria-label", `Stelle löschen: ${displayJobTitle(job.title)}`);
  remove.title = "Löschen · weniger ähnliche Jobs empfehlen";
  remove.addEventListener("click", () => onDelete(job));
  const actions = element("div", "card-actions");
  const like = element("button", `save-button like-button${job.liked ? " is-liked" : ""}`);
  like.type = "button";
  like.innerHTML = heart;
  like.setAttribute("aria-label", job.liked ? "Gefällt mir zurücknehmen" : "Gefällt mir · mehr ähnliche Jobs");
  like.setAttribute("aria-pressed", String(Boolean(job.liked)));
  like.title = like.getAttribute("aria-label");
  like.addEventListener("click", () => onLike(job));
  actions.append(like, save, remove);
  top.append(mark, identity, actions);
  card.append(top, element("h2", "card-title", displayJobTitle(job.title)));

  const match = element("p", "match-line");
  const matchSymbol = element("span", "match-symbol");
  matchSymbol.innerHTML = sparkles;
  match.append(matchSymbol, document.createTextNode(job.score ? `${job.score}/10 Passung mit deinem Profil` : "Passung noch nicht bewertet"));
  card.append(match);

  const chips = element("div", "card-chips");
  const hours = hoursLabel(job.hours);
  chips.append(chip(hours, /teilzeit/i.test(job.hours || "") ? "priority" : ""));
  const remote = remoteLabel(job);
  chips.append(chip(remote, /remote|hybrid/i.test(remote) ? "flexible" : ""));
  if (job.availability === "closed") chips.append(chip("Nicht mehr verfügbar", "caution"));
  card.append(chips);

  const fit = element("p", "card-fit", job.fit || job.summary || "Weitere Einzelheiten stehen in der Originalanzeige.");
  card.append(fit);

  const bottom = element("div", "card-bottom");
  const link = element("a", "card-cta", "Anzeige öffnen");
  link.insertAdjacentHTML("beforeend", externalLink);
  link.href = job.original_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const detail = element("button", "detail-button", "Details");
  detail.type = "button";
  detail.addEventListener("click", () => onOpen(job));
  const date = element("span", "card-date", relativeDate(job.first_seen_at));
  bottom.append(link, detail, date);
  card.append(bottom);
  return card;
}

export function showDetails(dialog, job, onStatus) {
  const target = dialog.querySelector("#dialog-content");
  target.replaceChildren();
  const save = dialog.querySelector("#dialog-save");
  const saved = job.user_status === "saved";
  save.innerHTML = bookmark;
  save.classList.toggle("is-saved", saved);
  save.setAttribute("aria-label", saved ? "Aus Merkliste entfernen" : "Stelle merken");
  save.setAttribute("aria-pressed", String(saved));
  save.title = save.getAttribute("aria-label");
  save.onclick = () => onStatus(job, saved ? "new" : "saved");
  const content = element("div", "dialog-content");
  const title = element("h2", "", displayJobTitle(job.title));
  title.id = "dialog-title";
  content.append(title, element("p", "dialog-company", job.company));
  const meta = element("div", "dialog-meta");
  const remote = remoteLabel(job);
  meta.append(chip(shortLocation(job.location)), chip(hoursLabel(job.hours)), chip(remote, /remote|hybrid/i.test(remote) ? "flexible" : ""));
  if (job.score) meta.append(chip(`${job.score}/10 Passung`, "priority"));
  content.append(meta);
  const companySection = element("section", "dialog-section company-profile");
  companySection.append(element("h3", "", "Über das Unternehmen"));
  if (job.company_description) {
    companySection.append(element("p", "", job.company_description));
    if (job.company_products) {
      companySection.append(element("h4", "", "Produkte & Dienstleistungen"), element("p", "", job.company_products));
    }
    if (/^https?:\/\//i.test(job.company_source_url || "")) {
      const citation = element("a", "company-profile-source", "Quelle zur Unternehmensbeschreibung");
      citation.href = job.company_source_url;
      citation.target = "_blank";
      citation.rel = "noopener noreferrer";
      citation.insertAdjacentHTML("beforeend", externalLink);
      companySection.append(citation);
    }
  } else {
    const undisclosed = /nicht offengelegt/i.test(job.company);
    companySection.append(element("p", "company-profile-pending", undisclosed
      ? "Der Arbeitgeber wurde in dieser Anzeige nicht offengelegt. Eine verlässliche Unternehmensbeschreibung ist deshalb nicht möglich."
      : "Eine geprüfte Unternehmensbeschreibung liegt noch nicht vor. Hermes ergänzt die Angaben schrittweise."));
  }
  content.append(companySection);
  const sections = element("div", "dialog-sections");
  const primary = element("div", "dialog-section-column");
  const secondary = element("div", "dialog-section-column");
  for (const [heading, body, column] of [["Aufgaben", job.summary, primary], ["Warum es passt", job.fit, secondary]]) {
    if (!body) continue;
    const section = element("section", "dialog-section");
    section.append(element("h3", "", heading), element("p", "", body));
    column.append(section);
  }
  const source = element("section", "dialog-section");
  source.append(element("h3", "", "Quelle und Funddatum"), element("p", "", `${job.source || "Originalanzeige"} · Gefunden am ${shortDate(job.first_seen_at) || "unbekannt"}${job.checked_at ? ` · Geprüft am ${shortDate(job.checked_at)}` : ""}`));
  secondary.append(source);
  if (!primary.childElementCount) primary.append(secondary.firstElementChild);
  sections.append(primary, secondary);
  content.append(sections);
  const actions = element("div", "dialog-actions");
  const link = element("a", "button-primary", "Originalanzeige öffnen");
  link.insertAdjacentHTML("beforeend", externalLink);
  link.href = job.original_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  actions.append(link);
  const hide = element("button", "button-secondary", job.user_status === "hidden" ? "Wieder anzeigen" : "Ausblenden");
  hide.type = "button";
  hide.addEventListener("click", () => onStatus(job, job.user_status === "hidden" ? "new" : "hidden"));
  actions.append(hide);
  content.append(actions);
  target.append(content);
  if (!dialog.open) dialog.showModal();
}
