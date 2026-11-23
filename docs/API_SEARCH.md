# Budgeted OpenAI API research

The optional `search-api` command uses the OpenAI Responses API with a separate
API key. Hermes may schedule it as a **no-agent script**: no Hermes model, Codex
OAuth session, fallback chain or auxiliary model participates in these searches.
The existing explicit profile, feedback, topic rotation, location rules,
employer/task screen, deduplication and daily import setting remain authoritative.

This mode is opt-in. Existing installations and fictional demos remain offline
unless explicitly configured and invoked. It adds no Python dependencies.

## Private configuration

Add this object to the ignored installation configuration, using your own private
absolute paths outside the checkout:

```json
"api_search": {
  "enabled": true,
  "credential_file": "/private-runtime/openai-api-key",
  "budget_file": "/private-runtime/api-search-budget.sqlite3",
  "monthly_budget_usd": 5,
  "min_interval_hours": 6,
  "max_candidates": 6,
  "max_web_searches": 2
}
```

Keep the key file owner-readable only (mode 600) in a private directory. Never put
keys in configuration examples, command arguments, scripts, logs or Git. The
program sends credentials only to the fixed HTTPS OpenAI Responses endpoint and
rejects redirects. Neither full API responses nor key fragments are logged.

## Cost and execution limits

The fixed model snapshot is `gpt-5-mini-2025-08-07`, reasoning effort `medium`, standard
processing. Standard prices were checked on 2026-11-23: $0.25/M input tokens,
$2/M output tokens and $0.01 per built-in web search. See the
[model](https://developers.openai.com/api/docs/models/gpt-5-mini),
[pricing](https://developers.openai.com/api/docs/pricing) and
[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
documentation. Recheck pricing before changing the model or rates.

The local SQLite ledger atomically reserves worst-case cost **before each paid
request**. Discovery reserves the full 400,000-token model context because the
search service adds context. Local verification reserves a conservative byte
bound on input. Every response has a 5,000-token output cap, including reasoning,
and discovery has a server-enforced tool-call limit. Charges include a 25% safety
margin; cached input discounts are deliberately ignored. Actual token usage and
search calls settle reservations. A timeout, missing usage or crash retains the
full reservation. A violated cost bound stops further calls for the month.

The budget covers **this Jobfind runner only**, not unrelated uses of the same API
project/key or taxes. It is a conservative local accounting limit, not the OpenAI
invoice. It depends on the documented fixed-model prices; do not silently change
models or processing tiers. Month boundaries use the configured installation
timezone. `api-budget` shows accounted cost, outstanding reservations and balance.

At six-hour spacing the hourly scheduler can start at most four API searches per
day. Intermediate checks are free and do not fabricate successful search records.
API topics rotate by attempt count, so six-hour spacing does not repeatedly select
the same subset of a six-topic hourly plan.
`--force` bypasses spacing for an explicit test, **never the monthly budget**.
When the budget is insufficient for the next worst-case reservation, that paid
request is skipped. New-job imports still have their independent configured
daily limit, including unlimited mode.

## Research and verification

One bounded API request discovers candidate URLs through live web search. Only
URLs present in returned search sources can progress. The local fetcher then
retrieves anonymous original advertisements with existing public-IP, redirect,
body-size and timeout protection. The existing PDF original-text extractor
requires a matching JobPosting or page heading; closed, inaccessible, known and
out-of-profile candidates are not imported.

A second request evaluates only fetched original texts and produces the existing
schema-1 result. It cannot introduce a new URL or employer. Titles must match the
fetched listing; harmless employer-name shortening is allowed, such as dropping a
parenthetical portal label. Explicit JobPosting metadata preserves location and
contract details outside the description. A proposed allowed location must also
occur in the original text or that metadata; search queries alone are not proof.
Location and
task/employer filters run again before import. Imported records retain the
existing saved/deleted-state behavior. Company portraits can use only those
fetched original sources; uncertain facts stay absent.

Page text and feedback are untrusted data, never instructions. No file access,
shell execution, messaging or application tools are exposed to the model. An
unverifiable search is an error rather than a fabricated successful empty run.
Structured execution reports are stored privately under `api-search-reports/`.

## Scheduler activation and rollback

Prepare a dedicated Hermes script invoking the canonical installation's Python
and `jobfind.py --config <private-config> search-api`. After tests, update only
the intended existing search job using `hermes cron edit <id> --script <name>
--no-agent`; preserve schedule and local delivery. No service or new LaunchAgent
is required. While this mode is enabled the importer skips Hermes `.md` execution
reports; API results are already imported directly. Existing JSON imports still
work.

Back up the previous job and private configuration before activation. To roll
back, disable `api_search.enabled` and restore that job's previous prompt, pre-run
script and agent mode. Existing jobs, feedback and bookmarks are unaffected.

Run `.venv/bin/python tests/check_api_search.py` for isolated budget, concurrency,
failure, source-grounding, import and credential-boundary checks. The test makes
no network calls; an actual provider test is a separate explicitly paid action.
