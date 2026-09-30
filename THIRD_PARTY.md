# Third-party notices and provenance

## SVG interface icons

The retained inline SVG paths in `index.html`, `login.html` and `assets/ui.js`
are attributed to Lucide by existing source comments; some shapes derive
from Feather. The original comment names v1.47.0, but that exact version
attribution was not independently established. No Lucide package is loaded
at runtime. Existing license texts and copyright notices are preserved
in full in `LICENSE-lucide.txt`.

The [official Lucide license page](https://lucide.dev/license) was checked on
September 30, 2026: ISC for Lucide, MIT for the listed Feather-derived icons.
These include search, link, trash, close and moon icons. Those notices apply
to the third-party components in addition to Jobfind's own MIT license.

## Fonts and company images

The package uses system fonts. The original private DIN Pro font files were
excluded because redistribution rights were not established. Curated company
logos, raster branding and potentially private image sources were also excluded
as app assets. Automatic logo fetching and its optional image libraries are
not included. Companies use a neutral interface icon.

`assets/brand-mark.svg` and `favicon.svg` were created for this package using
simple geometric shapes. No external images or manufacturer logos are used
as demo assets. Example jobs and company profiles are fictional; all external
example links use `example.org`. Mobile rendering of the SVG app icon still
needs manual verification.

## Live screenshots

`Screen-1.png` and `Screen-2.png` were supplied by the project owner and included
unchanged at the owner's request. They document the live installation with real
job listings, company names, logos and its existing typography. These elements
are shown only within the screenshots; their source assets are not bundled with
the app. Third-party trademarks and content remain subject to their respective
owners' rights and are not granted a new license by Jobfind's MIT license.
The screenshots illustrate appearance, not the completion of functional tests.

## Runtime

Python uses only its standard library. No vendored libraries, webfonts, CDN
scripts, frameworks or downloaded dependencies are included. Python, SQLite
and the optional Node.js test interpreter are installed separately.
Hermes is not copied into the project and is required only for automated
research. Its own license applies independently to the installed version.

## Project code

The code and documentation are MIT-licensed, as explicitly chosen by the
project owner. See `LICENSE`. The copyright notice is
`Copyright (c) 2026 Jobfind contributors`. Separate Lucide/Feather notices
are preserved; the external Hermes installation has its own license.
