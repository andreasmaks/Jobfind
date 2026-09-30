# Fremde Bestandteile und Herkunft

## SVG-Oberflächenicons

Die übernommenen Inline-SVG-Pfade in `index.html`, `login.html` und `assets/ui.js`
stammen laut bestehendem Quellhinweis aus Lucide; einige Formen sind von Feather abgeleitet.
Der ursprüngliche Kommentar nennt v1.47.0; diese konkrete Versionszuordnung wurde nicht
unabhängig belegt. Es wird kein Lucide-Paket nachgeladen. Lizenztexte und Urheberhinweise
aus dem Ausgangsprojekt bleiben vollständig in `LICENSE-lucide.txt` erhalten.

Die [offizielle Lucide-Lizenzseite](https://lucide.dev/license) wurde am 30.09.2026 geprüft:
ISC für Lucide, MIT für die dort aufgeführten Feather-Ableitungen. Dazu gehören unter
anderem Such-, Link-, Papierkorb-, Schließen- und Mond-Icons. Die Hinweise gelten für
diese Fremdbestandteile zusätzlich zur MIT-Lizenz für Jobfind selbst.

## Schrift und Unternehmensbilder

Das Paket verwendet Systemschriften. Die ursprünglichen privaten DIN-Pro-Dateien
wurden mangels nachgewiesener Weitergaberechte nicht übernommen. Kuratierte Firmenlogos,
Brand-Rasterbilder und mögliche private Bildquellen wurden ebenfalls nicht übernommen.
Der automatische Logoabruf samt optionalen Bildbibliotheken ist nicht Bestandteil
dieses Pakets. Unternehmen erhalten ein neutrales Oberflächensymbol.

`assets/brand-mark.svg` und `favicon.svg` wurden für dieses Paket aus einfachen geometrischen
Formen erstellt; keine externen Bilddateien oder Herstellerlogos dienen als Demo-Assets.
Die Beispieldaten und Unternehmensporträts sind erfunden, alle externen Beispiellinks
verwenden `example.org`. Das SVG-App-Icon muss auf mobilen Plattformen manuell geprüft werden.

## Laufzeit

Python verwendet ausschließlich die Standardbibliothek. Keine vendorten Bibliotheken,
Webfonts, CDN-Skripte, Frameworks oder heruntergeladenen Abhängigkeiten liegen im Paket.
Python, SQLite und der optionale Node.js-Testinterpreter bleiben extern installiert.
Hermes wird nicht kopiert und ist nur für automatische Recherche erforderlich;
seine Lizenz gilt unabhängig für die jeweilige Hermes-Installation.

## Eigener Code

Der eigene Code und die zugehörige Dokumentation stehen gemäß ausdrücklicher Wahl
des Projekteigentümers unter der MIT-Lizenz in `LICENSE`. Der Copyright-Hinweis lautet
`Copyright (c) 2026 Jobfind contributors`. Die gesonderten Hinweise für Lucide/Feather
bleiben vollständig erhalten; die Lizenz der externen Hermes-Installation bleibt unabhängig.
