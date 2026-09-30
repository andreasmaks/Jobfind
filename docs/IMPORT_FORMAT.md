# Result format 1

The existing JSON structure is retained. `schema_version` is the integer `1`.
The top level is an object with these fields; unknown fields and duplicate
JSON keys are rejected:

| Field | Rule |
| --- | --- |
| `schema_version` | Required: integer 1. |
| `run_status` | Required: `ok`, `empty` or `error`. |
| `jobs` | Required: array of at most 100 objects. `ok` requires at least one object; other statuses require `[]`. |
| `company_profiles` | Optional: at most eight profiles. Must be empty for `error`. |
| `error` | Optional: string up to 1000 characters. Required to be nonempty for `error`; do not include secrets. |
| `run_id` | Optional for JSON: your stable run identifier, 1–120 characters consisting of letters, digits, `_ . : -`. |
| `ran_at` | Optional: ISO-8601 timestamp with an explicit timezone. |

A JSON run with `run_id` is processed once. Without an ID, Jobfind uses the SHA-256
hash of the entire file. Different formatting changes the run identity but not
job deduplication. For Hermes Markdown, Jobfind always uses the configured Hermes
ID plus the filename timestamp, independently of model-supplied IDs. The filename
time is interpreted in the configured timezone, which must match Hermes.

Malformed files up to 1 MiB receive a neutral `invalid_result` error record when
their result type and identity can be established. Oversized files, inaccessible
files and invalid Hermes filenames are rejected earlier. Logs do not include
untrusted file contents. Processed runs, including invalid Hermes runs, are not
reapplied on every scan. Supply corrections as a **new run**, fixing the error
before generating a new ID.

## Job fields

`title`, `company` and `original_url` are required and must be nonempty.
`original_url` must use HTTP(S), have a host and contain no credentials.
Other allowed fields are:

- `source`, `source_id`, `location`, `remote`, `hours`, `employment_type`.
- `posted_at`, `checked_at`, `found_at` as text; dates are not automatically verified.
- `summary`, `fit`, `concerns` as plain text.
- `score`: optional, null or an integer from 1–10; booleans and numeric strings are invalid.
- `availability`: `active`, `unknown` or `closed`; default `unknown`.
- `work_model`: `remote`, `hybrid`, `onsite` or `unknown`; default `unknown`.

All text fields must be strings of at most 4000 characters. Storage applies
additional display-related limits, such as 250 characters for titles, 180 for
companies, 240 for locations and 2000 for summaries. `work_model` is used by the
importer for the explicitly enabled remote-location exception; the app displays
the descriptive `remote` field. Free text does not automatically establish a
remote exception.

URL normalization removes fragments, known tracking parameters and `utm_*`.
A reliable `source_id` is scoped to the source domain; without it, the canonical
URL identifies the job. URLs are also compared with all stored jobs. Duplicate
records are updated while retaining their first-seen time, status, likes and
rejection feedback. Rejected specific jobs do not reappear through the same URL
or source ID. Different domains/URLs without reliable IDs can still refer to
the same job; semantic deduplication and automatic merging are not provided.

## Company profiles

```json
{
  "company": "Demo Nordlicht Werkstatt",
  "description": "A fictional company supporting team processes.",
  "products": "Fictional organization tools.",
  "source_url": "https://example.org/demo-about",
  "status": "ready"
}
```

Only `company`, `description`, `products`, `source_url` and `status` are allowed.
Text fields allow at most 2000 characters. `status` is `ready` or `unknown`.
`ready` requires a description, products/services and an HTTP(S) source link.
For `unknown`, descriptive fields are kept empty rather than storing guesses.
Only profiles for already known companies or companies newly imported in the
same run are stored. Undisclosed employers are not guessed. An `unknown` update
does not replace an existing `ready` profile. Profiles are shared by jobs whose
literal company names normalize to the same value.

## Status and errors

```json
{"schema_version":1,"run_status":"empty","jobs":[],"company_profiles":[],"error":""}
```

```json
{"schema_version":1,"run_status":"error","jobs":[],"company_profiles":[],"error":"Fictional test error: research tool unavailable."}
```

`ok` remains a successful source run even when regional filters or the daily
limit exclude every new job. CLI output `region_filtered` counts location
exclusions; `count` counts newly stored jobs. `already_imported` identifies an
already processed run. `empty` is not an error. `error` preserves existing data
and gives exit code 1 for an initial single-file import. Any invalid record
invalidates the entire run before jobs or company profiles are changed.

Remaining daily slots are determined **inside the same SQLite write transaction**
as the import, using the actual import time in the configured timezone. Repeated
runs and existing-job updates do not count again. New candidates are sorted by
score. Jobs skipped because of the daily limit are not automatically deferred
to later days. Company profiles may be updated in an `empty` run, but not in an
`error` run. Existing jobs are never deleted because a run returns no jobs.
Error status and the last successful search are recorded separately.

Maximum file size: 1 MiB. Only UTF-8 JSON and the inspected Hermes Markdown
wrapper are accepted. Results cannot contain executable Python or Pickle;
historical free text is not interpreted heuristically.
