# Ergebnisformat 1

Das bestehende JSON-Grundformat bleibt erhalten. `schema_version` ist die ganze Zahl `1`.
Die obere Ebene ist ein Objekt mit folgenden Feldern; unbekannte Felder und doppelte
JSON-Schlüssel werden abgewiesen:

| Feld | Regel |
| --- | --- |
| `schema_version` | Pflicht: Integer 1. |
| `run_status` | Pflicht: `ok`, `empty` oder `error`. |
| `jobs` | Pflicht: Array, höchstens 100 Objekte. `ok` verlangt mindestens ein Objekt; andere Status verlangen `[]`. |
| `company_profiles` | Optional: höchstens acht Profile. Bei `error` muss das Array leer sein. |
| `error` | Optional: kurzer String bis 1000 Zeichen. Bei `error` nicht leer; keine Geheimnisse. |
| `run_id` | Optional für JSON: stabile eigene Laufkennung, 1–120 Zeichen aus Buchstaben, Ziffern, `_ . : -`. |
| `ran_at` | Optional: ISO-8601-Zeitstempel mit ausdrücklicher Zeitzone. |

Ein JSON-Lauf mit `run_id` wird genau einmal verarbeitet. Ohne ID verwendet Jobfind den
SHA-256-Hash der vollständigen Datei; eine andere Formatierung ändert diese Laufidentität,
aber nicht die Stellendublettenprüfung. Bei Hermes-Markdown verwendet Jobfind immer
konfigurierte Hermes-ID plus Dateizeitstempel, unabhängig von vom Modell gelieferten IDs.
Die Zeit aus dem Dateinamen wird in der konfigurierten, zu Hermes passenden Zeitzone gelesen.

Fehlerhafte Dateien bis 1 MiB erhalten einen neutralen Fehlerdatensatz `invalid_result`,
wenn sie zur Ergebnisart/Identität passen. Übergröße, fehlender Zugang zur Datei oder
ungültige Hermes-Dateinamen werden bereits davor abgewiesen. Protokolle enthalten keine
ungeprüften Inhalte der Datei. Bereits verarbeitete Läufe, einschließlich ungültiger
Hermes-Läufe, werden nicht bei jedem Scan wieder angewandt. Korrekturen als **neuen Lauf**
liefern; vor dem Erzeugen einer neuen ID Fehler beheben.

## Stellenfelder

`title`, `company`, `original_url` sind erforderlich und dürfen nicht leer sein.
`original_url` muss HTTP(S) mit Host und ohne Zugangsdaten sein. Weitere erlaubte Felder:

- `source`, `source_id`, `location`, `remote`, `hours`, `employment_type`.
- `posted_at`, `checked_at`, `found_at` als Textangaben (Datum nicht automatisch verifiziert).
- `summary`, `fit`, `concerns` als reine Texte.
- `score`: optional, null oder ganze Zahl 1–10; Bool und Zahlstrings sind ungültig.
- `availability`: `active`, `unknown` oder `closed`; Standard `unknown`.
- `work_model`: `remote`, `hybrid`, `onsite` oder `unknown`; Standard `unknown`.

Alle Textfelder sind Strings mit maximal 4000 Zeichen. Speicherung begrenzt einzelne
Felder zusätzlich passend zur Anzeige, z. B. Titel 250, Firma 180, Ort 240 und Zusammenfassung
2000 Zeichen. `work_model` ist ein Importmerkmal für die ausdrücklich erlaubte Remote-Ausnahme;
die App zeigt das beschreibende `remote`-Feld. Es gibt keine automatisch abgeleitete
Remote-Ausnahme aus einem frei formulierten Text.

URLs werden normalisiert: Fragmente, bekannte Tracking-Parameter und `utm_*` fallen weg.
Eine verlässliche `source_id` wird zusammen mit der Quell-Domain zur Identität; ohne ID
ist die kanonische URL maßgeblich. Zusätzlich wird die URL gegen alle gespeicherten
Stellen geprüft. Ein doppelter Datensatz wird aktualisiert, während Erstfund, Status,
Like und Ablehnungsfeedback erhalten bleiben. Abgelehnte konkrete Stellen werden weder
über dieselbe URL noch dieselbe Quell-ID wieder sichtbar. Unterschiedliche Domains/URLs
ohne verlässliche ID können semantisch gleiche Stellen bleiben; keine inhaltliche
Dubletten-Heuristik oder automatische Zusammenführung wird behauptet.

## Unternehmensprofile

```json
{
  "company": "Demo Nordlicht Werkstatt",
  "description": "Erfundenes Demo-Unternehmen für Teamprozesse.",
  "products": "Erfundene Organisationshilfen.",
  "source_url": "https://example.org/demo-about",
  "status": "ready"
}
```

Nur `company`, `description`, `products`, `source_url`, `status` sind erlaubt. Texte maximal
2000 Zeichen. `status` ist `ready` oder `unknown`. Bei `ready` sind Beschreibung,
Produkte/Dienstleistungen und HTTP(S)-Quellenlink erforderlich. `unknown` liefert keine
gespeicherten Vermutungen; Textfelder werden leer gehalten. Nur Profile bereits bekannter
oder im selben Lauf neu importierter Unternehmen werden gespeichert. Nicht offengelegte
Arbeitgeber werden nicht geraten. Ein `unknown`-Update verdrängt kein vorhandenes `ready`-Profil.
Profile sind geteilt zwischen Stellen desselben wörtlich normalisierten Firmennamens.

## Status und Fehler

```json
{"schema_version":1,"run_status":"empty","jobs":[],"company_profiles":[],"error":""}
```

```json
{"schema_version":1,"run_status":"error","jobs":[],"company_profiles":[],"error":"Erfundener Testfehler: Recherchewerkzeug nicht erreichbar."}
```

`ok` bleibt als erfolgreicher Quelllauf erkennbar, auch wenn Regionsfilter oder Tageslimit
alle neuen Stellen ausschließen. `region_filtered` in der CLI-Ausgabe zählt regionale
Ausschlüsse; `count` zählt neue gespeicherte Stellen. `already_imported` unterscheidet
einen bereits verarbeiteten Lauf. `empty` ist kein Fehler. `error` lässt vorhandene Daten
unverändert und führt bei einem erstmaligen Einzelimport zu Exit-Code 1. Auch ein ungültiger
Eintrag macht den ganzen Lauf ungültig, bevor Jobs oder Firmenprofile verändert werden.

Die verbleibenden Tagesplätze werden **in derselben SQLite-Schreibtransaktion** wie der
Import ermittelt, in der konfigurierten Zeitzone anhand der tatsächlichen Importzeit.
Wiederholungen und aktualisierte Bestandsstellen zählen nicht erneut. Neue Kandidaten
werden nach Score sortiert. Wegen des Tageslimits übersprungene neue Stellen werden nicht
automatisch auf spätere Tage verschoben. Firmenprofile dürfen bei `empty` aktualisiert
werden; bei `error` nicht. Es werden niemals bestehende Stellen gelöscht, weil ein Lauf
keine Stellen zurückliefert. Fehlerstatus und letzte erfolgreiche Suche sind getrennt.

Maximale Dateigröße: 1 MiB. Nur UTF-8-JSON und die geprüfte Hermes-Markdown-Hülle werden
gelesen; kein Pickle, kein Python aus Ergebnissen, kein historisches Freitext-Raten.
