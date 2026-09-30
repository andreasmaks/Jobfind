# Test status and pending checks

Prepared on **September 30, 2026**. Tested platform: macOS 27.0.1; Python 3.11.16
and 3.14.7. Node.js 26.9.0 was used only for the simulated offline check.
The app requires no additional runtime packages.

**Completed and passed:** all nine server/import/feedback groups with Python
3.11.16 and 3.14.7, fresh setup including demo and generated shims, and the
simulated offline check. The initial file audit after adding the MIT license
checked 39 intended files without findings. At that preparation stage, the
new local Git history contained zero commits and had no remote.
SHA-256 comparisons confirmed that 23 inspected original source files were
unchanged. Production job data, services and existing Hermes jobs were not modified.
The owner explicitly selected MIT on September 30, 2026; the license text and
third-party notices are included.

## Technical checks

Run these from the project directory. They use only temporary fictional data,
without opening a browser, researching with Hermes or contacting employers:

```sh
.venv/bin/python tests/check_release.py
.venv/bin/python tests/check_setup.py
node --experimental-vm-modules tests/check_offline.mjs
.venv/bin/python scripts/tools/audit_release.py
```

`check_release.py` covers nine focused groups:

1. Valid imports, repeated runs, existing-record updates without consuming new slots, and score ordering.
2. Concurrent imports enforcing the same daily limit.
3. Empty, failed and invalid runs; preserving existing jobs; size/type/URL validation.
4. Configurable place lists, exclusions and an explicit remote exception.
5. Daily boundaries in a timezone different from the host, independent of the stated search date.
6. Bookmarks alone, likes, separate rejection dimensions, notes as data, undo and URL/ID tombstones.
7. Fictional Hermes Markdown, file-stability delay and repeated directory scans.
8. Refusal of unrelated runtime directories without modifying their data.
9. HTTP startup on a free separate port, login, sessions, Origin/Host/CSRF checks,
   status/like/rejection/undo, invalid request bodies, sign-out and private-file protection;
   all static files needed for offline use are accessible.

`check_setup.py` copies only publication code to a temporary project directory
and checks a fresh `.venv`, configuration, password, import, repeated import,
locally generated and executed Hermes shims, a separate fictional demo, startup
on port 8124, and clean Ctrl+C shutdown. No shims are installed into a real
Hermes installation. Stop your own demo on port 8124 before running this check.

`check_offline.mjs` checks the actual shipped modules and queue functions with
small storage simulations: atomic action/snapshot writes, rollback on storage
failure, ordering, retaining and retrying failed actions, rejection/undo/like,
login instead of private offline fallback on 401, blocking sign-out while
actions are pending, cache cleanup, and Service Worker boundaries. Storage
stubs test logic; real Safari/browser transactions still need manual testing.

The audit checks an explicit publication list, UTF-8 content, symlinks, common
secret patterns and available Git objects. The two visually reviewed PNGs are
accepted only with their recorded SHA-256 hashes and PNG dimensions; no general
binary-file exception is enabled. Personal configuration, virtual
environments and runtime data are excluded. Manual content review is also
required; no scanner guarantees the absence of every form of personal data.

## Short manual browser checklist

Start the fictional demo with `jobfind.py demo`. Open it on the host itself or
through your own deliberately configured SSH tunnel; no new public endpoint is required.

- With your own demo password: sign in, try an incorrect password, sign out and sign in again.
- On desktop and a narrow mobile screen: check cards, filters, details, source links, dialogs and light/dark appearance.
- With the keyboard: check visible focus, cards/buttons, closing dialogs and undo; check the operating system's reduced-motion option.
- Online: bookmark and like a job; reject another for distance and hours with a fictional note, then undo.
- Wait for offline confirmation. Disconnect, reload, check details/filters, and store further actions including undo.
- Reconnect: the pending count should reach zero, and server state/context should reflect the final actions. Interrupted transfers must retain the queue.
- Sign out after synchronization and verify the offline copy is removed. For Safari/Home Screen mode, prepare that app context online and test it offline separately.

The owner positively confirmed an initial visual review of the demo. The full
browser checklist, real offline navigation, actual browser persistence, mobile
installation and Home Screen icon are **not yet verified**. An SVG app icon is
included; some platforms may benefit from an additional raster version.
The owner explicitly confirmed that real offline use and subsequent synchronization
have not been tested. This limitation remains documented for the first publication.

Documentation screenshots are illustrations and do not establish that offline
behavior or the publication package has passed the manual browser checklist.
Use fictional data for any further testing or public examples. Additional
publication of live data must be explicitly authorized by the owner.

## Decisions and remaining checks

- License selection is complete: MIT for project code and documentation;
  copyright `2026 Jobfind contributors`, with separate Lucide/Feather notices retained.
- Complete browser checks and document actual limitations.
- Approve and test a real Hermes search with your own configuration before
  calling end-to-end research verified. Hermes may transfer data externally and incur costs.
- Review contents and Git history. Do not add personal configuration, databases,
  logs, credentials or unreviewed assets.
- The GitHub target is the public repository `andreasmaks/Jobfind`. Creation and
  upload were separately and explicitly approved on September 30, 2026.
  This approval does not cover real Hermes searches.

Technical preparation can be completed independently of remaining checks.
Comprehensive release readiness is not claimed. The initial upload retains
the documented browser/research limitations. A separate GitHub release or
pull request was not part of the upload.

## Publication verification on September 30, 2026

The public repository is available at https://github.com/andreasmaks/Jobfind.
The first full upload contained exactly the 39 reviewed publication files;
its Git tree matched the prepared version. The project directory tracks
`origin/main`. The subsequent file/history audit reported no findings.

A fresh anonymous clone on the tested macOS system was checked in a temporary
directory: new virtual environment, configuration, password, valid example
import, duplicate-free reimport and separate demo preparation all passed.
The download check did not open a browser or run a Hermes search. The manual
limitations above remain in effect.

The owner subsequently requested English repository documentation while
retaining the German README, and supplied two screenshots of the live installation
for publication. The updated publication list contains 42 files: the original
39, the German README and the two unchanged PNGs. Both images were visually
reviewed against the supplied previews. They show real listings and the owner's
live hostname, as explicitly requested; no credentials or private notes were visible.
This documentation update does not translate the app interface or change runtime
behavior. Real offline use and synchronization remain unverified.

Reviewed screenshot SHA-256 hashes:

- `Screen-1.png`: `cb256e6fbd888622b750b23d1e38fd1fc1739795bc13b4f85c3d40eb9ba27176`
- `Screen-2.png`: `66ebfc7f97b195367375076a02962ec8d30320eaa2c672917cc27ed3cb1b6d85`
