# Prüfstand und Freigabepunkte

Vorbereitung am **30.09.2026**. Geprüfte Plattform: macOS 27.0.1; Python 3.11.16 und
3.14.7. Node.js 26.9.0 wurde nur für den nicht browserbasierten Offline-Prüflauf benutzt.
Der eigene Code verwendet keine zusätzlichen Laufzeitpakete.

**Ausgeführt und bestanden:** alle neun Server-/Import-/Feedback-Prüfgruppen mit Python
3.11.16 und 3.14.7, frische Installation einschließlich Demo und erzeugter Shims sowie
die simulierte Offline-Prüfung. Der Dateiaudit nach Ergänzung der MIT-Lizenz prüfte 39 vorgesehene Dateien
ohne Fund; zum Zeitpunkt dieses Vorbereitungsaudits enthielt die neue lokale
Git-Historie null Commits und keinen Remote.
23 gelesene Originalquelldateien wurden per SHA-256 unverändert abgeglichen.
Produktivdaten, Dienste und vorhandene Hermes-Aufträge wurden nicht verändert.
Die MIT-Lizenz wurde am 30.09.2026 auf ausdrückliche Wahl des Projekteigentümers ergänzt;
Lizenztext und Drittanbieterhinweise sind enthalten.

## Durchführbare technische Prüfungen

Die Skripte werden im Projektordner aufgerufen und erzeugen ausschließlich temporäre,
erfundene Daten. Kein Browser, kein Hermes-Recherchelauf und keine Arbeitgeberkontakte:

```sh
.venv/bin/python tests/check_release.py
.venv/bin/python tests/check_setup.py
node --experimental-vm-modules tests/check_offline.mjs
.venv/bin/python scripts/tools/audit_release.py
```

`check_release.py` deckt neun gezielte Gruppen ab:

1. Gültiger Import, Wiederholung, Bestandsaktualisierung ohne erneutes Tagesbudget und Score-Auswahl.
2. Gleichzeitige Importe halten dasselbe Tageslimit ein.
3. Leerer, fehlerhafter und ungültiger Lauf; vorhandene Stellen bleiben erhalten; Größen-/Typ-/URL-Prüfung.
4. Geänderte Ortsliste, regionale Ausschlüsse und ausdrückliche Remote-Ausnahme.
5. Tagesgrenze in einer vom Host abweichenden Zeitzone, unabhängig vom angegebenen Suchdatum.
6. Merken ohne andere Signale, Like, Ablehnungsdimensionen, Notiz als Daten, Rückgängig und Tombstones bei URL-/ID-Wiederholung.
7. Erfundenes Hermes-Markdown, Stabilitätswartezeit und wiederholter Ordnerscan.
8. Abweisung fremder Laufzeitverzeichnisse ohne deren Daten zu verändern.
9. HTTP-Start auf freiem getrenntem Port, Anmeldung, Session, Origin/Host/CSRF,
   Status/Like/Ablehnung/Rückgängig, ungültige Schreibkörper, Abmelden und Schutz privater Dateien;
   sämtliche für Offline benötigten statischen Dateien sind abrufbar.

`check_setup.py` kopiert nur Veröffentlichungscode in einen neuen temporären Projektordner:
frische `.venv`, eigene Konfiguration, Passwort, Import, Wiederholungsimport, lokal erzeugte
und ausgeführte Hermes-Shims, eigene erfundene Demo, Start auf Port 8124 und sauberer Stopp
mit Ctrl+C. Keine Shims werden dabei in eine echte Hermes-Installation kopiert.

`check_offline.mjs` prüft die tatsächlich ausgelieferten Module und Warteschlangenfunktionen
mit bewusst kleinen Speichersimulationen: atomare Aktion/Snapshot-Speicherung, Rollback bei
Speicherfehlern, Reihenfolge, Beibehalten und Wiederholen fehlgeschlagener Aktionen,
Ablehnung/Rückgängig/Like, Anmeldung statt privater Offline-Fallback bei 401, blockiertes
Abmelden bei offenen Aktionen, Cachebereinigung und Grenzen des Service Workers.
Die Speicherattrappen prüfen Logik; konkrete Safari-/Browser-Transaktionen bleiben manuell offen.

Der Audit prüft alle vorgesehenen Dateien gegen eine feste Veröffentlichungsliste,
UTF-8-Inhalt, Symlinks und gängige Geheimnismuster sowie gegebenenfalls vorhandene Git-Objekte.
Private Konfiguration, virtuelle Umgebung und Laufzeitdaten sind explizit keine
Veröffentlichungsdateien. Manuelle Sichtung zusätzlich erforderlich; kein Scanner garantiert
die Abwesenheit jeder Art persönlicher Daten.

## Kurze manuelle Browserprüfung

Mit `jobfind.py demo` die erfundene Demo starten. Nur auf dem Host selbst oder über einen
bewusst eingerichteten eigenen SSH-Tunnel öffnen; kein neuer öffentlicher Zugang erforderlich.

- Eigenes Demo-Passwort: anmelden, falsches Passwort testen, abmelden und erneut anmelden.
- Desktop und schmaler mobiler Bildschirm: Karten, Filter, Details, Quellen, Dialoge und ruhiges Hell/Dunkel-Design prüfen.
- Tastatur: sichtbarer Fokus, Karten/Buttons, Dialog schließen und Rückgängig; Betriebssystemoption „Bewegung reduzieren“ prüfen.
- Online eine Stelle merken und liken; andere mit Entfernung und Arbeitszeit plus erfundener Notiz ablehnen, anschließend Rückgängig.
- Offline-Bestätigung abwarten. Verbindung deaktivieren, App neu laden, Details/Filter prüfen und weitere Aktionen inklusive Rückgängig speichern.
- Wieder verbinden: Zähler muss auf null sinken, Serverzustand und Kontext müssen den letzten Aktionen entsprechen; bei unterbrochener Übertragung bleibt die Warteschlange erhalten.
- Abmelden: erst nach Synchronisierung, Offline-Kopie anschließend entfernt. Bei Safari/Home-Bildschirm die App dort ebenfalls einmal online vorbereiten und erneut offline prüfen.

Eine erste Sichtprüfung der Demo wurde vom Projekteigentümer positiv bestätigt. Die
vollständige Browsercheckliste, echte Offline-Navigation, tatsächliche Browserpersistenz,
mobile Installation und Home-Bildschirm-Icon sind **noch nicht verifiziert**. Ein SVG-App-Icon ist enthalten;
je nach Plattform kann eine gesonderte Raster-Icon-Fassung sinnvoll sein.
Der Projekteigentümer hat ausdrücklich bestätigt, dass die echte Offline-Nutzung und
spätere Synchronisierung bisher nicht geprüft wurden; diese Einschränkung bleibt für
die erste Veröffentlichung dokumentiert.

Geeignete spätere Screenshots ausschließlich aus der Demo: Übersicht mit vier erfundenen
Stellen, Detail mit Demo-Unternehmensporträt, Ablehnungsdialog ohne persönliche Notiz und
Offline-Anzeige mit erfundenen ausstehenden Aktionen. Hier wurden keine Screenshots erstellt.

## Vor einer Veröffentlichung entscheiden

- Lizenzentscheidung abgeschlossen: MIT für den eigenen Code und die zugehörige Dokumentation;
  Copyright `2026 Jobfind contributors`, gesonderte Lucide-/Feather-Hinweise erhalten.
- Browsercheck abschließen und tatsächliche Einschränkungen dokumentieren.
- Echte Hermes-Suche separat freigeben und mit eigener Konfiguration prüfen, bevor
  End-to-end-Recherchefunktion als getestet bezeichnet wird. Hermes kann externe Datenflüsse und Kosten auslösen.
- Inhalte und Git-Historie final sichten. Keine private Konfiguration, Datenbank, Logs,
  Zugangsdaten oder ungeprüften Assets hinzufügen.
- GitHub-Ziel und Sichtbarkeit sind festgelegt: öffentliches Repository
  `andreasmaks/Jobfind`. Anlegen und Upload wurden am 30.09.2026 gesondert ausdrücklich
  freigegeben. Die Freigabe umfasst keine echten Hermes-Suchläufe.

Die technische Vorbereitung kann unabhängig von diesen Entscheidungen abgeschlossen
werden. Eine pauschale vollständige Veröffentlichungsreife wird nicht behauptet.
Der erste Upload erfolgt mit den oben dokumentierten offenen Browser- und
Rechercheprüfungen. Ein gesonderter Release oder Pull Request ist nicht Teil dieses Uploads.
