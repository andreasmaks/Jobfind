# Jobfind with Hermes integration

[Deutsch](README.de.md)

For an existing live installation, see [the development workflow](docs/DEVELOPMENT.md):
one checkout holds the shared code; local settings, assets and data stay private.

Jobfind is a lightweight, self-hosted web app for a personal job search. It is designed
for one person who wants to review a small selection of relevant jobs and give specific
feedback for the next search.

Search profile and previous feedback → Hermes research → structured import →
Jobfind listings → likes, bookmarks and rejection reasons → context for the next search.
Feedback adjusts the search context; it does not train the underlying model.
Improved match quality and market uniqueness have not been demonstrated.

**Status:** an initial MIT-licensed publication with technical checks completed.
Full browser testing and a live Hermes search are still pending. This is a
Hermes extension package with file-based integration, not an official Hermes plugin.
The app interface, CLI messages, example content and generated search context are
currently in German. Repository documentation is available in English, with a German README.

## Screenshots

![Job overview in the live installation, with search, match scores and bookmarks](Screen-1.png)

*Discover jobs and compare their fit with your search profile.*

![Job details in the live installation, with company information, tasks and match explanation](Screen-2.png)

*Review company information, responsibilities and the reason a job matches.*

## Features

- Job overview, text search, and filters for work model, working hours, match score and hidden jobs.
- Job details, validated HTTP(S) links to original listings, and optional company profiles with sources.
- Bookmarks, independent likes, hiding, and rejection with multiple reasons and an optional 600-character note.
- Undo for rejections made in the current session, restoring the previous status and feedback.
- Import with URL/source-ID deduplication, run identity and a configurable daily limit.
- A local offline copy and ordered synchronization of user actions when reconnected.

Hermes researches jobs. Jobfind supplies the profile and feedback context, validates
results, and stores jobs and user actions in SQLite. The app, manual imports and
fictional demo work without Hermes. Automatic applications, application-document
generators and multi-user hosting are outside the scope of this release.

## Requirements and tested environment

- **Python 3.11 or newer**, including `venv`, SQLite and timezone data.
- Tested on **macOS 27.0.1**, with **Python 3.11.16 and 3.14.7**. The main test run
  used **SQLite 3.53.4**. Linux, Windows and Docker have not been verified.
- No additional Python packages, npm installation or build pipeline is required to run the app.
  `requirements.txt` documents the absence of third-party Python dependencies.
- A modern browser with JavaScript. Offline use requires IndexedDB, Service Workers and
  Cache Storage on `localhost`/loopback or HTTPS; actual browser behavior still needs manual testing.
- Optional for automated research: your own configured Hermes installation with a model
  provider and research tools. Local integration was checked against **Hermes Agent v0.21.4
  (2026.9.21), commit c80d12b9**. CLI help and source interfaces were inspected;
  no live search was run. Hermes is not bundled. See [integration instructions](docs/HERMES.md).

## Installation and personal setup

Clone the repository, or download and extract its ZIP from GitHub:

```sh
git clone https://github.com/andreasmaks/Jobfind.git
cd Jobfind
```

Run the following commands from the project directory. Install Python first if
`python3 --version` does not report a suitable version.

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python jobfind.py init
.venv/bin/python jobfind.py doctor
```

`init` creates `config/jobfind.json` without overwriting existing files. Edit your
search profile there, then set **your own password** and start the app:

```sh
.venv/bin/python jobfind.py password
.venv/bin/python jobfind.py start
```

By default, the app is available at **http://127.0.0.1:8123** on the same computer.
It runs in the foreground; **Ctrl+C** stops it. `scripts/start_server.sh` is an
alternative entry point after creating `.venv`. Setup does not install a background
service, proxy or public endpoint. There are no built-in credentials.
Passwords must contain 12–256 characters; interactive entry is hidden and requested
twice. Changing the password ends all existing server sessions.

Use `--config /path/to/your.json` **before** the subcommand, or set `JOBFIND_CONFIG`,
to select a different configuration. Legacy `JOBPORTAL_*` variables are not used.

### Search profile

`config/example.json` contains fictional places and neutral preferences. Replace
them before performing a real search:

| Field | Meaning |
| --- | --- |
| `search.region.allowed_places` | Literal allowed place names; at least one is required. |
| `excluded_places` | Hard exclusions, including listings mentioning several locations. |
| `ambiguous_labels` | Vague regional labels that do not count as a specific workplace. |
| `allow_remote_without_local_place` | Only when `true` may verified `work_model: remote` be imported without an allowed place. Excluded locations still take precedence. |
| `roles`, `activities` | Desired roles and tasks. |
| `weekly_hours`, `work_models` | Explicit working-hours and work-model preferences for Hermes. |
| `hard_exclusions` | Mandatory content exclusions in the research context. |
| `soft_preferences` | Preferences to weight rather than treat as bans. |
| `max_new_jobs_per_day` | 1–100 new records per calendar day in `timezone`. |
| `hermes.job_id`, `output_dir`, `schedule` | Your Hermes job, its output directory and desired interval. `schedule` is not automatically applied to Hermes. |
| `data_dir` | Your runtime directory. Relative paths are resolved from the configuration file. |
| `server.bind`, `port`, `public_origin` | Local IPv4 loopback only; port 1024–65535. An HTTPS origin is for a proxy you deliberately configure yourself. |
| `timezone` | IANA timezone, such as `Europe/Berlin`, for the daily limit and Hermes filename timestamps. |

Location checks and the daily limit are enforced by the importer. Tasks, working hours
and content exclusions guide Hermes; they are not semantic filters in the importer.
Review results yourself. Place names are matched as bounded words and may include
districts. There is no geocoding or radius calculation. Maintain your own list of
nearby places. Regions, ambiguous labels and exclusions are configurable. Keep free
text in structured profile fields brief.

Configuration changes take effect on the next CLI/server start. Hermes reloads the
profile on its next pre-run call. Searches already in progress may use the previous
context. Restart the app after changing ports, data paths or server settings.

## Demo without Hermes

```sh
.venv/bin/python jobfind.py demo
```

Set your own demo password on first use. The demo loads four fictional jobs and two
fictional company profiles. It uses `config/demo.json`, `.runtime/demo/`, and
**http://127.0.0.1:8124**. Its data and credentials are separate from your personal
setup. Starting it again does not overwrite passwords or feedback. Demo links point
to `example.org`; they are not real vacancies. Example dates are fictional. No
employers are contacted and no model calls are made. `demo --prepare-only` prepares
the demo without starting its server.

## Importing results

```sh
.venv/bin/python jobfind.py import /path/to/result.json
```

A minimal fictional result, retaining the fictional place name used by the example configuration:

```json
{
  "schema_version": 1,
  "run_id": "fictional-run-1",
  "run_status": "ok",
  "error": "",
  "jobs": [{
    "title": "Project assistant",
    "company": "Demo Nordlicht Werkstatt",
    "original_url": "https://example.org/jobs/1",
    "source_id": "1",
    "location": "Beispielstadt",
    "hours": "Teilzeit, 28 Stunden/Woche",
    "summary": "A fictional job for trying the app.",
    "score": 8
  }],
  "company_profiles": []
}
```

The location must match your configuration. See [the import format](docs/IMPORT_FORMAT.md)
for all optional fields and error rules. `examples/demo.json`, `empty.json` and
`error.json` contain fictional test data. The importer makes no network requests
and does not download company logos or images.

`ok` means the source search succeeded and found jobs; regional filters, duplicates
and the daily limit may still result in zero new records. `empty` means a successful
search with no jobs; `error` means a failed run. Empty or failed results never remove
existing jobs. A malformed record invalidates the entire run before any job or
company-profile changes. Invalid content receives a neutral error status.

The daily limit counts only **new** records at the actual import time in the
configured timezone. Updates, duplicates and rejected jobs do not consume slots.
SQLite serializes concurrent imports. Higher-scoring candidates are preferred.
A processed run is not applied again; candidates excluded by the limit are not
automatically queued for the following day.

## Likes, bookmarks and rejections

A heart is an explicit positive signal. A bookmark is a weaker signal of interest.
Hiding removes a job from the normal view without generating rejection feedback.
Rejecting removes it from all views while retaining a record for feedback and
deduplication; it does not physically erase the record.

Rejection reasons apply to their specific dimensions. Distance does not devalue
the tasks, and unsuitable hours do not devalue the industry. A single rejection
does not establish a general ban. Repeated consistent signals may receive more
weight. Current explicit preferences take precedence over indirect inferences.
Context output separates the profile from untrusted listings, company descriptions
and notes. This limits prompt-injection exposure but cannot guarantee protection
for every model.

Undo removes active negative feedback and restores the previous status. It is
available for rejections made in the open session; there is no persistent recovery
overview after a full reload. Active likes survive restoration. Search context
contains at most 60 active rejections, 60 active likes, 20 bookmarked jobs and 240
known jobs. Import deduplication checks all stored duplicates and rejections,
regardless of those context limits.

## Offline use and synchronization

The interface follows the browser's primary language preference: German (`de`,
including regional variants) stays German; every other language uses English.
This includes sign-in, dialogs, feedback, status messages and dates, also offline.
Original job text, company information and personal notes are not machine-translated.
Reload after changing the device/browser language; no translation service is used.

Sign in online and keep the page open briefly so app files and the current job
snapshot can be stored in the browser. Preparation runs in the background without
a permanent status banner; pending changes and errors are still shown. Before
relying on offline access, disconnect and reload to check your device. Search,
filters and details are available offline. Bookmarks,
likes, rejections, hiding and undo are stored locally and sent in order after
reconnection. Network failures preserve the queue; server actions are idempotent
on retry. An action may be skipped if its job is no longer available; the app
reports this. Sign-out requires synchronization first and removes the local
offline copy. Sign in again if your session has expired.

Original listings and company sources require Internet access. Browsers may remove
stored data under storage pressure. Offline data is not additionally encrypted
and is not a backup; use a locked personal device. Run separate personal setups
on **different ports/origins**, since browser storage is shared within an origin.
Safari, Home Screen mode, mobile layout and actual airplane-mode use still need
browser testing. See [the manual checklist](docs/RELEASE_CHECKLIST.md).

## Data, security and operation

The default personal setup stores data in `.runtime/personal/`; the demo uses
`.runtime/demo/`. Files include `jobs.sqlite3`, password verifier `auth.json`,
sessions in `auth.sqlite3`, and `.csrf_secret`. Runtime directories use permissions
700 and sensitive files 600. Do not put secrets in profiles, prompts or results.
Do not place passwords in the repository or command line. For automated setup,
provide passwords through stdin from your own secure mechanism.

An existing nonempty data directory without Jobfind's runtime marker is refused
to prevent accidental access to unrelated data. A new installation does not adopt
existing private databases. Existing marked Jobfind runtime directories can be
reused; do not copy the marker into unrelated directories.

Sessions are hashed server-side and time-limited. Login checks the origin and
rate-limits failed attempts; modifying API calls and sign-out check the origin
and CSRF token. Untrusted text is rendered as text. The server serves only
explicitly allowed app files. Local HTTP uses HttpOnly/SameSite cookies; a
deliberately configured HTTPS proxy origin additionally enables Secure. A proxy
must preserve Host and Origin. Remote access, TLS and proxy setup are not
automated or verified end to end.

**Self-hosted does not mean entirely local:** during Hermes research, your profile,
feedback, notes and relevant existing jobs may be sent to the configured model
provider or other research services. Review those services' privacy terms and
costs. The app has no telemetry, external fonts or automatic logo fetching.
Following an external link deliberately connects to its operator.

For backups, synchronize pending browser actions and stop the app and your
import process. Back up your runtime directory and private configuration together,
including SQLite WAL files where applicable. Protect copies containing password
verifiers and sessions. For recovery, configure the same marked data path, stop
all processes before copying, then restart.

Stop the app with Ctrl+C. No LaunchAgent is installed. Remove optional dedicated
Hermes jobs and shims individually as described in [the Hermes guide](docs/HERMES.md).
Project code can be removed after backing up your data. Personal configuration
and runtime data are never automatically deleted.

## Troubleshooting and limitations

| Problem | Action |
| --- | --- |
| Missing configuration | Run `jobfind.py init`; place `--config` before the subcommand. |
| Port already in use | Stop your own instance or configure another free port; check `doctor`. |
| Missing/forgotten password | Run `jobfind.py password` with your own configuration. |
| Unrelated data directory | Choose a new empty directory; never add a runtime marker to unrelated data. |
| No imported jobs | Check locations, exclusions, daily budget and run identity. Examples use fictional places. |
| Invalid output | Check the schema and provide corrected content as a new run. No unstructured Markdown or `[SILENT]`. |
| Missing Hermes output folder | Configure your own job ID and its actual output directory; do not reuse other jobs. |
| Offline unavailable | Use loopback or HTTPS, reload online and wait for the storage confirmation. Browser support or storage may be limited. |
| 401/403 during synchronization | Sign in again and use the correct origin/port. Other origins are not allowed by CORS. |
| Missing Home Screen icon | Neutral SVG icons are supplied; check platform rendering manually. |

The part-time filter looks for the explicit German word “Teilzeit”; weekly hours
alone do not prove a part-time arrangement. Scores come from the result supplier
and are not objective quality measurements. Company profiles remain incomplete
without verified sources. The original automatic logo search is disabled in this
package; neutral icons avoid additional image-rights questions and external requests.

## Checks and publication

```sh
.venv/bin/python tests/check_release.py
.venv/bin/python tests/check_local.py
.venv/bin/python tests/check_setup.py
# Optional Node.js check; not required to run the app:
node --experimental-vm-modules tests/check_offline.mjs
node --experimental-vm-modules tests/check_i18n.mjs
.venv/bin/python scripts/tools/audit_release.py
```

Checks use fictional data in separate temporary directories. The setup check starts
a temporary demo on port 8124; stop your own demo before running that check.
The offline check simulates browser storage and transfer, so it does not replace
actual browser testing. See [test status and pending checks](docs/RELEASE_CHECKLIST.md).

Personal configuration, runtime data and `.venv` are excluded. Review all intended
files and Git history before uploading; `.gitignore` alone is insufficient. The
audit checks an explicit file list and common secret patterns, but does not
replace final human review. The check scripts do not upload or publish anything.

## License

The project code and documentation are licensed under **MIT**, as explicitly
chosen by the project owner. See [LICENSE](LICENSE) for the complete license and
copyright notice, and the [Open Source Initiative](https://opensource.org/license/mit)
for its official text.

Lucide/Feather SVG icons retain their ISC/MIT notices in `LICENSE-lucide.txt`.
See [third-party notices and asset provenance](THIRD_PARTY.md). Hermes is an
external prerequisite with its own license and is not bundled.
