# Applications

Optional outgoing automation is documented in [Automatic applications](AUTO_APPLY.md).
Its pending queue is separate from confirmed applications and their counts.

Bookmarked listings appear only in Saved, not in All. A listing linked to a
confirmed application whose current effective status is Rejected is excluded
from every job list, saved counters and bookmark PDF exports. Its job metadata,
bookmark and application history are retained for the Applications view. This
display rule is not deletion feedback. Uncertain mail matches do not suppress
listings. A corrected application status restores the normal list placement.

The Applications view tracks applications to listings found by Jobfind and their email evidence. Linking an application to a listing does not change its bookmark or deletion state. Unrelated mailbox history is ignored and excluded from lists, counts and detail APIs. Explicitly added manual entries remain available.

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

Mailboxes are opened read-only; messages are fetched using `BODY.PEEK`. The integration never sends, moves or deletes email and never changes read flags. The first run searches application-related subjects across the configured folders. A bounded batch is processed per folder; remaining matches continue on subsequent runs. Later runs inspect new messages and thread references. A message creates an automatic record only if it matches a known portal listing or supplies a plausible listing candidate. Follow-ups to unrelated old applications are ignored. Applications predating the listing's first appearance in Jobfind are excluded, with a one-day margin for date differences. A later message at the same employer does not turn an old application into a new portal application.

## Recognition and correction

Permanent delivery-status notifications are matched by **original Message-ID and
recipient** against the private outbound intent. They create the distinct orange
**Not delivered** status, not a hiring rejection or an employer receipt. Failed
delivery therefore does not hide a listing from job lists. The outgoing attempt
remains blocked from automatic retry. Generic rejection prose, unmatched reports,
temporary 4.x delays and delivery reports for other recipients do not qualify.
An employer's genuine review/interview/decision remains stronger evidence than a
transport failure. A later actual receipt can supersede a failed initial attempt.

The reader revisits a bounded seven-day window of delivery-report subjects when
capacity remains in its normal batch, so recently skipped bounces are recognized
after an update. It retains incremental checkpoints, idempotence and BODY.PEEK.

Explicit receipts, rejections, offers and other clear application messages establish an application. Ambiguous recruiting messages remain in **Needs review** until confirmed. This is a local rule-based recognizer, so unusual wording can require manual correction. Quoted email history is excluded from status detection. Message IDs deduplicate copies across folders; thread references combine replies, including out-of-order imports. A delayed receipt does not reopen a more advanced application status.

Listings are linked automatically only with strong, unique evidence: an exact listing URL or both employer and role. Old applications are not automatically linked to newly found listings. Company-only matches are suggestions that require confirmation. Users can correct the company, role, listing, note and status; a manual status overrides later automatic updates until changed back to **Automatic from emails**. Ignoring a false positive retains its deduplication record, so it does not reappear on the next scan.

The private application database lives in the configured data directory, separately from the listings database. It stores only relevant message metadata and short text excerpts, not attachments or full mailbox copies. The authenticated APIs use `private, no-store` and require same-origin CSRF protection for changes. The service worker never caches mail APIs. Offline storage retains only application list metadata, without message excerpts, notes or mail subjects; signing out clears it together with the existing offline data. Older offline snapshots without portal scope are rejected. Email evidence is displayed as inert text.

## Verification

```sh
python tests/check_applications.py
node --experimental-vm-modules tests/check_applications.mjs
node --experimental-vm-modules tests/check_offline.mjs
node --experimental-vm-modules tests/check_i18n.mjs
```

These checks use temporary databases, fictional messages and an IMAP fake; they never contact a real mailbox. Check the live mobile layout and a representative application manually after deployment.
