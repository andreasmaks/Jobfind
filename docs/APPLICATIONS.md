# Applications

The Applications view keeps an independent record of applications and their email evidence. Linking an application to a listing does not change its bookmark or deletion state. It also works for applications whose listings were never found by Jobfind.

## Mail connection

Add an optional `applications_mail` object to the ignored installation configuration:

```json
{
  "applications_mail": {
    "enabled": true,
    "host": "imap.example.org",
    "port": 993,
    "username": "your-mailbox@example.org",
    "credential_file": "/absolute/private/path/outside/the/repository/mail-password",
    "folders": [
      {"name": "INBOX", "sent": false},
      {"name": "Archive", "sent": false},
      {"name": "Sent", "sent": true}
    ],
    "max_messages_per_folder": 250
  }
}
```

Use the actual folder names from your provider. The password file must be outside the project and accessible only to its owner (mode `600`). Use an app-specific password when required by the provider. The connection uses TLS with certificate validation. Mail contents and credentials are never sent to an AI provider.

Run `python jobfind.py --config config/jobfind.json sync-applications` from a scheduler, or use the authenticated **Sync emails** button. A 15-minute schedule is suitable. The command reports only counts and fixed error codes. It locks concurrent runs. A failed run retains existing applications and resumes from the last successful folder checkpoint.

Mailboxes are opened read-only; messages are fetched using `BODY.PEEK`. The integration never sends, moves or deletes email and never changes read flags. The first run searches application-related subjects across the configured folders, including old messages. A bounded batch is processed per folder; older history continues on subsequent runs. Later runs inspect new messages and thread references. There is no arbitrary age cutoff on application history.

## Recognition and correction

Explicit receipts, rejections, offers and other clear application messages establish an application. Ambiguous recruiting messages remain in **Needs review** until confirmed. This is a local rule-based recognizer, so unusual wording can require manual correction. Quoted email history is excluded from status detection. Message IDs deduplicate copies across folders; thread references combine replies, including out-of-order imports. A delayed receipt does not reopen a more advanced application status.

Listings are linked automatically only with strong, unique evidence: an exact listing URL or both employer and role. Old applications are not automatically linked to newly found listings. Company-only matches are suggestions that require confirmation. Users can correct the company, role, listing, note and status; a manual status overrides later automatic updates until changed back to **Automatic from emails**. Ignoring a false positive retains its deduplication record, so it does not reappear on the next scan.

The private application database lives in the configured data directory, separately from the listings database. It stores only relevant message metadata and short text excerpts, not attachments or full mailbox copies. The authenticated APIs use `private, no-store` and require same-origin CSRF protection for changes. The service worker never caches mail APIs. Offline storage retains only application list metadata, without message excerpts, notes or mail subjects; signing out clears it together with the existing offline data. Email evidence is displayed as inert text.

## Verification

```sh
python tests/check_applications.py
node --experimental-vm-modules tests/check_applications.mjs
node --experimental-vm-modules tests/check_offline.mjs
node --experimental-vm-modules tests/check_i18n.mjs
```

These checks use temporary databases, fictional messages and an IMAP fake; they never contact a real mailbox. Check the live mobile layout and a representative application manually after deployment.
