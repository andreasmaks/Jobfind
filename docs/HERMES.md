# Hermes integration

Jobfind uses a small file-based boundary: profile/feedback → Hermes research →
schema-1 result → Jobfind import. Hermes is not copied into the package, no
plugin API is invented, and no model provider is configured automatically.
Another supplier could later produce the same result format without a provider framework.

The inspected local version is Hermes Agent v0.21.4 (2026.9.21), commit c80d12b9.
`hermes --version`, `hermes cron create --help`, `edit --help` and `remove --help`,
plus the implementation of pre-run scripts and local delivery, were checked.
Inspect the CLI help before using a different version. The
[official cron documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron/)
describes pre-run context and local delivery; newer documentation may use different
tool names. This package uses the CLI options actually inspected.

**Package preparation did not create, change or activate Hermes jobs, and did not
make model calls.** The instructions below let you create your own separate jobs.
A real search requires your explicit decision about providers, data transfers
and costs. Leave existing jobs unchanged.

The app interface, CLI messages and generated context currently remain in German.
The bundled research prompt also remains in German; the instructions below explain
its setup in English without changing its research behavior.

## Without automation

```sh
.venv/bin/python jobfind.py context
```

Output contains the current explicit profile, remaining daily slots and feedback
separated by dimension. You can use it with `hermes/prompt.txt` for a deliberately
started Hermes run. Save the final schema-1 answer as `.json` and import it with
`jobfind.py import /your/path/result.json`.
Context output contains private data: keep it out of repositories and public logs.

## Prepare your own cron integration

1. Set up Hermes using its [official instructions](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart/).
   Check the provider, research tools and scheduler readiness yourself. Jobfind
   must not replace existing credentials or global services.
2. Set up Jobfind with your own configuration and password. Enter your actual search profile.
3. Run this in the project directory:

   ```sh
   .venv/bin/python jobfind.py hermes-prepare
   ```

   This generates `hermes-setup/jobfind-context.py`, `jobfind-import.py` and `prompt.txt`
   only inside your runtime directory. The small shims use your specific Python
   interpreter and configuration. If you move the project or `.venv`, inspect the
   existing helpers before deliberately regenerating them. `hermes-prepare` does
   not overwrite existing helpers with different content.
4. For the default configuration, locate your Hermes scripts directory and install
   helpers under **dedicated new names**. Check that another installation does not
   already use these names. `cp -n` prevents overwriting:

   ```sh
   JOBFIND_HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
   mkdir -p "$JOBFIND_HERMES_HOME/scripts"
   cp -n .runtime/personal/hermes-setup/jobfind-context.py "$JOBFIND_HERMES_HOME/scripts/jobfind-release-context.py"
   cp -n .runtime/personal/hermes-setup/jobfind-import.py "$JOBFIND_HERMES_HOME/scripts/jobfind-release-import.py"
   ```

   With a different `data_dir`, use the source paths printed by `hermes-prepare`.
   Inspect existing destination files and choose distinct names if needed.
   Hermes runs `.py` scripts with its Python; each shim explicitly invokes Jobfind's Python.
5. Create your own **paused** research job. This example uses a 24-hour interval;
   deliberately substitute your desired `hermes.schedule` value:

   ```sh
   hermes cron create "every 24h" "$(cat hermes/prompt.txt)" \
     --name "Jobfind Release - Search" --deliver local --paused \
     --script jobfind-release-context.py
   ```

   The inspected CLI supports `--paused`, `--script` and `--deliver local`.
   The pre-run shim supplies fresh profile and feedback context for every run.
   The prompt is neutral; preferences come from configuration. CLI output gives
   your **new job ID**. Record it safely; never substitute an existing job's ID.
6. Set the corresponding values in `config/jobfind.json`:

   ```json
   "hermes": {
     "job_id": "YOUR_NEW_ID",
     "output_dir": "~/.hermes/cron/output/YOUR_NEW_ID",
     "schedule": "every 24h"
   }
   ```

   `output_dir` must match the actual Hermes home/profile. Use its absolute path
   for a nondefault `HERMES_HOME`. Hermes determines its output directory; Jobfind
   does not change it. The configured ID identifies Markdown runs for deduplication.
   For Hermes Markdown, Jobfind's timezone must match the output filename's timezone.
   Alternatively, import JSON with an explicit ISO timestamp and timezone.

## Import and subsequent activation

With an output directory and existing results:

```sh
.venv/bin/python jobfind.py import
```

The scan reads `.json` and Hermes `.md` files at least 60 seconds old. Hermes
Markdown must contain the actual `## Response` section and use a
`YYYY-MM-DD_HH-MM-SS.md` filename. Historical free text, `[SILENT]` and incomplete
results are not guessed to mean a successful empty run. Original result files
are left unchanged. JSON runs need a stable `run_id` or receive a content-hash
identity. Correct a processed result by supplying a new run.

Optionally, a **second separate paused job** can run only the importer without
an agent or model:

```sh
hermes cron create "every 5m" --name "Jobfind Release - Import" \
  --script jobfind-release-import.py --no-agent --deliver local --paused
```

Record its new ID separately. Only after explicitly approving real research,
deliberately activate the intended IDs:

```sh
hermes cron resume YOUR_SEARCH_ID
hermes cron resume YOUR_IMPORT_ID
```

Hermes manages the research interval. Changing `hermes.schedule` in Jobfind alone
does not modify a job. Apply later changes explicitly with the inspected command:

```sh
hermes cron edit YOUR_SEARCH_ID --schedule "every 24h"
```

A manually triggered search may also make paid model and research calls.
Activation and live execution were not tested here. CLI construction and local
shims were checked; an end-to-end research run remains pending approval and testing.

Search context has size limits. Even when older specific rejections are no longer
in context, the database prevents their reimport. Concurrent searches may still
use older preferences. Newly imported jobs are additionally subject to the current
location rules and daily budget. Review content-based profile rules yourself.

## Remove only your optional integration

First verify the recorded IDs belong to **this** installation. Pause and remove
only those jobs:

```sh
hermes cron pause YOUR_SEARCH_ID
hermes cron pause YOUR_IMPORT_ID
hermes cron remove YOUR_SEARCH_ID
hermes cron remove YOUR_IMPORT_ID
```

Hermes may clean up a job's associated output when removing it; back up required
results first. Inspect and remove only the dedicated shim files installed above.
Do not run blanket deletion commands for `~/.hermes`, other jobs, gateway services,
LaunchAgents or provider credentials. Jobfind's personal database remains intact.
Stop the app separately with Ctrl+C. Jobfind does not install a LaunchAgent.
