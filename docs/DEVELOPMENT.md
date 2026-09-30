# Working on a live installation

Use one Git checkout for the application. Keep installation settings and data out of Git:

| Location | Purpose | Published |
| --- | --- | --- |
| Application files | Shared code, documentation and tests | Yes |
| `config/live.json` | Server, search and Hermes settings | No |
| `.private/` | Local fonts, logos, profile and optional hooks | No |
| Data directory selected by configuration | Listings, feedback and authentication | No |
| `logs/` | Service logs | No |

Start the live service with an explicit configuration:

```sh
python jobfind.py --config config/live.json start
```

For a feature change, use a temporary Git worktree so editing does not change files served by the running application:

```sh
git worktree add -b feature/my-change ../jobfind-change
```

The worktree starts without private configuration or data. Use `jobfind.py demo --prepare-only` there and run the release, offline and fresh-install checks described in the README. Never point a test configuration at the live data directory.

After reviewing the change, commit it, merge it into the live checkout, restart the service and check its health. Publish the same commit to GitHub. Remove the temporary worktree when finished. A change appears on GitHub only after it has been pushed.

Before publishing, stage the intended files and run:

```sh
python scripts/tools/audit_release.py
git diff --cached --stat
git status --short
```

The audit checks a publication allowlist and Git history. Adding a public file requires updating that allowlist. Ignored files that are accidentally forced into Git still fail the audit.

## Optional local appearance

The `local` object in an ignored configuration may contain `presentation_file`, `assets_dir`, `profile_file`, `session_cookie`, `legacy_run_ids` and `import_hook`. Paths are relative to the configuration file. Public installations do not require these options.

The presentation JSON has three keys: `assets`, `company_logos` and `part_time_terms`. Each asset maps a permitted same-origin URL to a relative file and a `public` boolean. Only files inside `assets_dir` are served. Company logo entries reference those URLs and may specify `mode` and `dark_url`. `part_time_terms` adds local working-hours labels to the part-time filter.

`profile_file` supplies additional owner-authored search instructions. `session_cookie` lets an existing installation keep its session cookie name. `legacy_run_ids` retains old Hermes filename identifiers and accepts the previous empty-result format during migration.

`import_hook` executes an owner-controlled Python file after a scheduled import scan and calls its `sync_company_logos(limit=4, verbose=False)` function. Configure it only for a local integration you trust; it can access local data and the network.

Existing data directories require the Jobfind ownership marker. Do not add it to an unrelated folder. When migrating an older installation, back up both databases, verify their schema and preserve the existing authentication files before adopting the directory.
