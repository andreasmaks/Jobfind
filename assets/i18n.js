// UI language follows the browser's primary device-language preference. No data leaves the device.
(() => {
  const preferred = navigator.languages?.[0] || navigator.language || "de";
  const language = /^de(?:-|$)/i.test(preferred) ? "de" : "en";
  const locale = language === "de" ? "de-DE" : "en-GB";
  const english = {
    "jobfind · Anmelden": "jobfind · Sign in",
    "jobfind, zur Stellenübersicht": "jobfind, job overview",
    "Hauptnavigation": "Main navigation",
    "Alle": "All", "Gemerkte": "Saved", "Archiv": "Archive",
    "Informationen und Einstellungen": "Information and settings",
    "Hell": "Light", "Dunkel": "Dark",
    "Helles Design einschalten": "Switch to light appearance",
    "Dunkles Design einschalten": "Switch to dark appearance",
    "Abmelden": "Sign out", "Anmelden": "Sign in",
    "Stand: {date}": "Updated: {date}",
    "Stellensuche": "Job search", "Stellenübersicht": "Job overview",
    "Anzahl der Jobs wird geladen": "Loading job count",
    "Stellen durchsuchen": "Search jobs",
    "Titel, Unternehmen oder Ort suchen": "Search title, company or location",
    "Filter": "Filters", "Arbeitsmodell": "Work model", "Arbeitszeit": "Working hours",
    "Remote möglich": "Remote available", "Hybrid": "Hybrid",
    "Teilzeit ausdrücklich genannt": "Part-time explicitly offered",
    "Vollzeit möglich": "Full-time available",
    "Bewertung": "Rating", "Alle Bewertungen": "All ratings",
    "Ab 7 von 10": "7 out of 10 or higher", "Ab 8 von 10": "8 out of 10 or higher",
    "Ab 9 von 10": "9 out of 10 or higher", "Sortierung": "Sort by",
    "Neueste zuerst": "Newest first", "Beste Passung": "Best match",
    "Unternehmen A–Z": "Company A–Z", "Sichtbarkeit": "Visibility",
    "Sichtbare Stellen": "Visible jobs", "Ausgeblendete Stellen": "Hidden jobs",
    "Hier ist noch Platz für etwas Gutes.": "Room for something good.",
    "Sobald Hermes passende Stellen findet, erscheinen sie hier.": "Jobs will appear here when Hermes finds suitable matches.",
    "Für diese Auswahl gibt es noch keine Stellen. Passe die Suche oder Filter an.": "No jobs match this selection. Adjust your search or filters.",
    "Gelöschte Stelle": "Deleted job", "Rückgängig": "Undo",
    "Deine Empfehlungen werden persönlicher": "Your recommendations get more personal",
    "Was passt hier nicht?": "What doesn't work for you?",
    "Wähle aus, was dich stört. Hermes berücksichtigt deine Gründe bei neuen Empfehlungen.": "Choose what doesn't work for you. Hermes uses your reasons for future recommendations.",
    "Gründe": "Reasons", "· optional, mehrere möglich": "· optional, select any that apply",
    "Fachbereich": "Field", "Unternehmen": "Company", "Entfernung": "Distance",
    "Aufgaben": "Responsibilities", "Präsenz / Remote": "On-site / remote",
    "Gehalt": "Salary", "Erfahrungslevel": "Experience level", "Sonstiges": "Other",
    "Was wäre dir lieber?": "What would you prefer?", "Optional": "Optional",
    "Zum Beispiel: Mehr Produktkonzeption, weniger reine Screenproduktion.": "For example: More product strategy, less screen production.",
    "Behalten": "Keep", "Löschen & Feedback speichern": "Delete & save feedback",
    "Wird gespeichert …": "Saving …", "Schließen": "Close",
    "Stelle merken": "Save job", "Aus Merkliste entfernen": "Remove from saved jobs",
    "Stelle löschen: {title}": "Delete job: {title}",
    "Löschen · weniger ähnliche Jobs empfehlen": "Delete · recommend fewer similar jobs",
    "Gefällt mir zurücknehmen": "Remove like", "Gefällt mir · mehr ähnliche Jobs": "Like · more similar jobs",
    "{score}/10 Passung mit deinem Profil": "{score}/10 match with your profile",
    "{score}/10 Passung": "{score}/10 match", "Passung noch nicht bewertet": "Match not yet rated",
    "{from}–{to} Std.": "{from}–{to} hrs", "ab {hours} Std.": "from {hours} hrs",
    "{hours} Std.": "{hours} hrs", "Teilzeit möglich": "Part-time available",
    "Vollzeit": "Full-time", "Stunden offen": "Hours unspecified",
    "Arbeitsmodell offen": "Work model unspecified", "Ort nicht angegeben": "Location unspecified",
    "Nicht mehr verfügbar": "No longer available",
    "Weitere Einzelheiten stehen in der Originalanzeige.": "Further details are in the original listing.",
    "Anzeige öffnen": "Open listing", "Details": "Details", "Heute": "Today", "Gestern": "Yesterday",
    "Über das Unternehmen": "About the company", "Produkte & Dienstleistungen": "Products & services",
    "Quelle zur Unternehmensbeschreibung": "Company information source",
    "Der Arbeitgeber wurde in dieser Anzeige nicht offengelegt. Eine verlässliche Unternehmensbeschreibung ist deshalb nicht möglich.": "The employer is not disclosed in this listing, so reliable company information is unavailable.",
    "Eine geprüfte Unternehmensbeschreibung liegt noch nicht vor. Hermes ergänzt die Angaben schrittweise.": "Verified company information is not available yet. Hermes adds it gradually.",
    "Warum es passt": "Why it fits", "Quelle und Funddatum": "Source and discovery date",
    "Originalanzeige": "Original listing", "Gefunden am {date}": "Found on {date}",
    "Geprüft am {date}": "Checked on {date}", "unbekannt": "unknown",
    "Originalanzeige öffnen": "Open original listing", "Wieder anzeigen": "Show again", "Ausblenden": "Hide",
    "{count} Job": "{count} job", "{count} Jobs": "{count} jobs",
    "{count} Job in dieser Auswahl": "{count} job in this selection",
    "{count} Jobs in dieser Auswahl": "{count} jobs in this selection",
    "Der letzte Suchlauf hatte einen Fehler. Frühere Treffer bleiben sichtbar.": "The last search failed. Earlier results remain visible.",
    "{count} Änderung lokal gespeichert. Wird beim Verbinden übertragen.": "{count} change saved locally. It will sync when reconnected.",
    "{count} Änderungen lokal gespeichert. Wird beim Verbinden übertragen.": "{count} changes saved locally. They will sync when reconnected.",
    "{count} Offline-Änderung wird übertragen …": "Syncing {count} offline change …",
    "{count} Offline-Änderungen wird übertragen …": "Syncing {count} offline changes …",
    "{count} Änderung noch nicht übertragen.": "{count} change not yet synced.",
    "{count} Änderungen noch nicht übertragen.": "{count} changes not yet synced.",
    "{count} Änderung wartet auf Übertragung.": "{count} change waiting to sync.",
    "{count} Änderungen wartet auf Übertragung.": "{count} changes waiting to sync.",
    "{count} Änderung entfiel, weil die Stelle nicht mehr verfügbar ist.": "{count} change was skipped because the job is no longer available.",
    "{count} Änderungen entfielen, weil die Stelle nicht mehr verfügbar ist.": "{count} changes were skipped because the jobs are no longer available.",
    "Bitte später erneut verbinden; deine Änderungen bleiben auf diesem Gerät gespeichert.": "Please reconnect later; your changes remain saved on this device.",
    "Offline-Kopie konnte nicht gespeichert werden. Bitte lade die Seite mit Internet erneut.": "The offline copy could not be saved. Please reload with an Internet connection.",
    "Die Änderung konnte nicht gespeichert werden. Bitte versuche es erneut.": "The change could not be saved. Please try again.",
    "„{title}“ gelöscht. {detail}": "“{title}” deleted. {detail}",
    "Wird nach dem Verbinden übertragen.": "It will sync when reconnected.",
    "Hermes berücksichtigt das bei künftigen Empfehlungen.": "Hermes will use this for future recommendations.",
    "Dein Gefällt mir konnte nicht gespeichert werden. Bitte versuche es erneut.": "Your like could not be saved. Please try again.",
    "Das Feedback konnte nicht gespeichert werden. Bitte versuche es erneut.": "Your feedback could not be saved. Please try again.",
    "Die Stelle konnte nicht wiederhergestellt werden. Bitte versuche es erneut.": "The job could not be restored. Please try again.",
    "Zum Abmelden bitte erst wieder mit dem Internet verbinden.": "Please reconnect to the Internet before signing out.",
    "Offline-Änderungen konnten noch nicht übertragen werden. Bitte später erneut abmelden.": "Offline changes could not be synced yet. Please try signing out later.",
    "Die Offline-Kopie konnte nicht entfernt werden. Bitte versuche es erneut.": "The offline copy could not be removed. Please try again.",
    "Die Stellen konnten nicht geladen werden. Bitte lade die Seite erneut.": "Jobs could not be loaded. Please reload the page.",
    "Bitte versuche es gleich noch einmal.": "Please try again shortly.",
    "DEIN PRIVATER JOB-SCOUT": "YOUR PRIVATE JOB SCOUT", "Willkommen": "Welcome", "zurück.": "back.",
    "Melde dich mit deinem jobfind-Passwort an, um deine Stellen zu sehen.": "Sign in with your jobfind password to see your jobs.",
    "Passwort": "Password", "Das Passwort war nicht richtig.": "The password was incorrect.",
    "Zu viele Versuche. Bitte warte kurz und versuche es erneut.": "Too many attempts. Please wait a moment and try again.",
  };
  function t(source, values = {}) {
    const text = language === "en" && Object.hasOwn(english, source) ? english[source] : source;
    return text.replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(values, name) ? String(values[name]) : match);
  }
  let pageTranslated = false;
  function translatePage() {
    if (pageTranslated || !document.body) return;
    pageTranslated = true;
    document.documentElement.lang = language;
    document.title = t(document.title);
    // Only initial HTML, before listings are rendered. Never translate stored job/user content.
    const walker = document.createTreeWalker(document.body, 4 /* SHOW_TEXT */);
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement?.closest("script, style")) continue;
      const original = node.textContent.trim();
      if (original) node.textContent = node.textContent.replace(original, t(original));
    }
    document.querySelectorAll("[aria-label], [title], [placeholder]").forEach((node) => {
      for (const name of ["aria-label", "title", "placeholder"]) {
        const value = node.getAttribute(name);
        if (value) node.setAttribute(name, t(value));
      }
    });
  }
  window.JobfindI18n = { language, locale, t, translatePage };
  document.documentElement.lang = language;
  document.addEventListener("DOMContentLoaded", translatePage, { once: true });
})();
