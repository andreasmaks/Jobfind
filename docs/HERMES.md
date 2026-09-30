# Hermes-Anbindung

Jobfind verwendet eine kleine dateibasierte Grenze: Profil/Feedback → Hermes-Recherche →
Schema-1-Ergebnis → Jobfind-Import. Es gibt kein kopiertes Hermes, keine erfundene
Plugin-API und keinen automatisch konfigurierten Modellanbieter. Ein anderer Lieferant
könnte später dasselbe Ergebnisformat schreiben, ohne ein Anbieter-Framework zu benötigen.

Der geprüfte lokale Stand ist Hermes Agent v0.21.4 (2026.9.21), Commit c80d12b9.
`hermes --version`, `hermes cron create --help`, `edit --help` und `remove --help`
sowie die Implementierungen von Pre-Run-Skripten und lokaler Ausgabe wurden gelesen.
Vor Verwendung einer anderen Version deren CLI-Hilfe prüfen. Die
[offizielle Cron-Dokumentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron/)
beschreibt Pre-Run-Kontext und lokale Lieferung; neuere Dokumentation kann andere
Toolnamen enthalten. Dieses Paket verwendet die tatsächlich geprüften CLI-Optionen.

**Während der Paketvorbereitung wurden keine Hermes-Aufträge angelegt, verändert oder
aktiviert und keine Modellaufrufe ausgeführt.** Die folgenden Schritte richten später
eigene getrennte Aufträge ein. Ein echter Suchlauf benötigt die ausdrückliche Entscheidung
des Betreibers über Anbieter, Datenfluss und Kosten. Bestehende Aufträge unverändert lassen.

## Ohne Automatisierung

```sh
.venv/bin/python jobfind.py context
```

Die Ausgabe enthält das aktuelle ausdrückliche Profil, verbleibende Tagesplätze und
dimensioniertes Feedback. Sie kann zusammen mit `hermes/prompt.txt` für einen bewusst
gestarteten eigenen Hermes-Lauf verwendet werden. Die finale Schema-1-Antwort als `.json`
speichern und mit `jobfind.py import /eigener/pfad/ergebnis.json` importieren.
Kontextausgaben enthalten private Daten: nicht im Repository oder in öffentlichen Logs speichern.

## Eigene Cron-Anbindung vorbereiten

1. Hermes selbst nach dessen [offizieller Anleitung](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart/)
   einrichten. Geeigneten Anbieter, Recherchewerkzeuge und Schedulerbereitschaft selbst prüfen.
   Keine vorhandenen Zugangsdaten oder globalen Dienste durch Jobfind ersetzen.
2. Jobfind mit eigener Konfiguration und Passwort einrichten. Das tatsächliche Suchprofil pflegen.
3. Im Projektordner ausführen:

   ```sh
   .venv/bin/python jobfind.py hermes-prepare
   ```

   Das erzeugt nur im eigenen Datenverzeichnis `hermes-setup/jobfind-context.py`,
   `jobfind-import.py` und `prompt.txt`. Die beiden kleinen Shims verwenden den konkreten
   Python-Interpreter und die eigene Konfiguration. Verschiebt man das Projekt oder die
   `.venv`, die vorhandenen Hilfsdateien zunächst prüfen und anschließend bewusst neu erzeugen.
   `hermes-prepare` überschreibt abweichende vorhandene Hilfsdateien nicht.
4. Für die Standardkonfiguration den eigenen Hermes-Skriptordner bestimmen und die
   Hilfsdateien unter **dedizierten neuen Namen** installieren. Erst prüfen, dass diese Namen
   dort nicht schon von einer anderen Einrichtung benutzt werden. `cp -n` überschreibt nichts:

   ```sh
   JOBFIND_HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
   mkdir -p "$JOBFIND_HERMES_HOME/scripts"
   cp -n .runtime/personal/hermes-setup/jobfind-context.py "$JOBFIND_HERMES_HOME/scripts/jobfind-release-context.py"
   cp -n .runtime/personal/hermes-setup/jobfind-import.py "$JOBFIND_HERMES_HOME/scripts/jobfind-release-import.py"
   ```

   Bei anderem `data_dir` die von `hermes-prepare` ausgegebenen Quellpfade verwenden.
   Bei bestehenden Zieldateien Inhalt prüfen und eindeutige andere Namen wählen.
   Hermes führt `.py`-Skripte mit seinem Python aus; der Shim ruft explizit Jobfinds Python auf.
5. Einen **pausierten** eigenen Rechercheauftrag anlegen. Das Beispielintervall ist 24 Stunden;
   den gewünschten Wert aus `hermes.schedule` bewusst einsetzen:

   ```sh
   hermes cron create "every 24h" "$(cat hermes/prompt.txt)" \
     --name "Jobfind Release - Suche" --deliver local --paused \
     --script jobfind-release-context.py
   ```

   Die CLI hat im geprüften Stand `--paused`, `--script` und `--deliver local`.
   Der Pre-Run-Shim liefert Profil und Feedback frisch für jeden Lauf. Prompt-Inhalte sind
   neutral; Nutzerwünsche kommen aus der Konfiguration. Die CLI-Ausgabe nennt die **neue eigene
   Auftrags-ID**. Diese ID sicher notieren, keine ID eines bestehenden Auftrags einsetzen.
6. In `config/jobfind.json` setzen:

   ```json
   "hermes": {
     "job_id": "EIGENE_NEUE_ID",
     "output_dir": "~/.hermes/cron/output/EIGENE_NEUE_ID",
     "schedule": "every 24h"
   }
   ```

   `output_dir` muss zum tatsächlichen Hermes-Home/Profile passen; bei abweichendem
   `HERMES_HOME` dessen absoluten Pfad verwenden. Hermes bestimmt seinen Ausgabeordner;
   Jobfind ändert ihn nicht. Die Konfigurations-ID kennzeichnet Markdown-Läufe für die
   Deduplizierung. Die Zeitzone von Jobfind muss bei Hermes-Markdown zur Hermes-Ausgabezeit
   passen. Alternativ JSON mit ausdrücklichem ISO-Zeitstempel und Zeitzone importieren.

## Import und spätere Aktivierung

Mit einem Ergebnisordner und vorhandenen Ausgaben:

```sh
.venv/bin/python jobfind.py import
```

Die Prüfung liest `.json`- und Hermes-`.md`-Dateien, die mindestens 60 Sekunden alt sind.
Hermes-Markdown muss den tatsächlichen `## Response`-Abschnitt und Dateinamen
`YYYY-MM-DD_HH-MM-SS.md` besitzen. Historischer Freitext, `[SILENT]` und unvollständige
Ausgaben werden nicht als erfolgreicher leerer Lauf geraten. Originaldateien werden
nicht verändert. Neue JSON-Läufe benötigen eine stabile `run_id` oder erhalten eine
Inhalts-Hash-Identität. Für Korrekturen einer verarbeiteten Datei einen neuen Lauf liefern.

Optional kann ein **zweiter eigener pausierter** Hermes-Auftrag ausschließlich den Import
ohne Agent/Modell ausführen:

```sh
hermes cron create "every 5m" --name "Jobfind Release - Import" \
  --script jobfind-release-import.py --no-agent --deliver local --paused
```

Auch dessen neue ID getrennt notieren. Erst nach eigener ausdrücklicher Freigabe für den
Recherchebetrieb die dafür vorgesehenen IDs bewusst aktivieren:

```sh
hermes cron resume EIGENE_SUCH_ID
hermes cron resume EIGENE_IMPORT_ID
```

Das Rechercheintervall wird durch Hermes verwaltet. Eine spätere Änderung von
`hermes.schedule` in Jobfind allein ändert keinen Auftrag; mit dem geprüften
`hermes cron edit EIGENE_SUCH_ID --schedule "every 24h"` gezielt nachführen.
Ein manuell ausgelöster Suchlauf kann ebenfalls kostenpflichtige Modell- und Rechercheaufrufe
auslösen. Hier wurde weder Aktivierung noch Live-Ausführung getestet. CLI-Konstruktion und
lokale Shims sind geprüft; der End-to-end-Recherchelauf ist ein offener Freigabepunkt.

Der maximale Suchkontext ist begrenzt. Wenn alte konkrete Ablehnungen nicht mehr im Kontext
stehen, verhindert die Datenbank dennoch deren erneuten Import. Gleichzeitig laufende
Suchen können alte Wünsche sehen; importierte neue Stellen bleiben zusätzlich durch das
aktuelle technische Orts-/Tagesbudget begrenzt. Inhaltliche Profilregeln selbst prüfen.

## Ausschließlich die eigene optionale Integration entfernen

Zuerst anhand der notierten IDs verifizieren, dass beide Aufträge zu **dieser** Einrichtung
gehören. Dann ausschließlich diese pausieren und entfernen:

```sh
hermes cron pause EIGENE_SUCH_ID
hermes cron pause EIGENE_IMPORT_ID
hermes cron remove EIGENE_SUCH_ID
hermes cron remove EIGENE_IMPORT_ID
```

Hermes kann beim Entfernen seine zugehörigen Laufdateien aufräumen; benötigte eigene
Ausgaben vorher sichern. Nur die eigenen oben installierten Shimdateien nach Sichtung
entfernen. Keine pauschalen Befehle für `~/.hermes`, keine fremden Jobs, Gateway-Dienste,
LaunchAgents oder Anbieterzugänge löschen. Jobfinds persönliche Datenbank bleibt erhalten.
App separat mit Ctrl+C stoppen. Es gibt keinen von Jobfind installierten LaunchAgent.
