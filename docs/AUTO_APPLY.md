# Automatic applications

`jobfind.py auto-apply` selects visible listings rated **strictly above 8** (9–10).
It skips deleted/hidden listings and existing applications, including closed,
ignored and candidate-linked records. It never changes bookmarks.

This initial adapter supports **explicit email application routes**. It can
recognize a recruiting mailbox inside a structured JobPosting description when
nearby text explicitly requests an email application and its domain matches the
employer's listing domain. Generic pages, footers and shared ATS mailboxes do not
qualify. Additional routes can be explicitly reviewed and configured below.
It does not yet submit arbitrary ATS forms. Portal/login/CAPTCHA workflows remain
pending in the Applications view, rather than being counted as applications.
Unverified or expired listings remain pending as well. No credentials are created,
no sensitive answers are guessed and no general support/footer address is used.

Add to the ignored installation configuration:

```json
{"auto_apply": {"enabled": true,
  "profile_file": "/absolute/private/path/application-profile.json",
  "routes": {"known-job-id": {
    "url": "https://employer.example/apply",
    "recipient": "applications@employer.example",
    "proof": "Please send your application by email"
  }}
}}
```

Every route requires owner review of the actual employer application page.
Each run rechecks the listing identity, expiry and current route evidence. The
mail link and proof sentence must still be present. New portals need a dedicated
adapter before unattended delivery is possible; a generic language model is not
used to fill or submit unknown forms.

The private profile must live outside the repository with mode `600`:

```json
{
  "name": "Your Name", "email": "you@example.org", "phone": "+00 123456",
  "address": "Your postal address", "available_from": "2027-01-01",
  "salary_eur_year": 60000,
  "introduction": {"de": "Eigene belegte berufliche Erfahrung.", "en": "Your factual professional experience."},
  "documents": {
    "de": {"cv": "/private/cv-de.pdf", "portfolio": "/private/portfolio-de.pdf", "combined": "/private/combined-de.pdf"},
    "en": {"cv": "/private/cv-en.pdf", "portfolio": "/private/portfolio-en.pdf", "combined": "/private/combined-en.pdf"}
  },
  "smtp": {"host": "smtp.example.org", "port": 587,
    "username": "you@example.org", "credential_file": "/private/mail-password"}
}
```

Use employer-specific, accurate introductions only. No private values belong in Git.
English listing text uses English documents; otherwise German. Email attaches the
CV, plus the portfolio when work samples/portfolio are requested. Combined PDFs
are validated for future single-file portal adapters. There is no PDF rewriting.
The desired annual gross salary is included when the listing asks for salary.

SMTP uses verified STARTTLS and authentication. Before SMTP DATA the outbox commits
a durable uncertainty marker. A crash, timeout or ambiguous answer at that point
**never triggers an automatic resend**. Check the mailbox/provider before clearing
such a record. A confirmed SMTP acceptance creates a linked application with a
submission event; this is not an employer receipt. Incoming receipts and later
replies continue through the existing read-only mailbox sync.

A later permanent bounce changes the application to **Not delivered** and the
outbox intent to `failed`. It is not an employer rejection. A failed intent is
never automatically resent, even if its application record was removed. SMTP
acceptance alone must not be presented as proof of receipt by the employer.

The outbox is stored in the private application database. The authenticated API
exposes only job identity, fixed state/reason codes and check time. Pending items
are omitted from offline application snapshots. No documents or SMTP settings
are served. No language model, paid API call or Codex session is used by this worker.

## Operation

```sh
python jobfind.py --config config/jobfind.json auto-apply --dry-run
python jobfind.py --config config/jobfind.json auto-apply
python jobfind.py --config config/jobfind.json application-outbox
python tests/check_auto_apply.py
```

Dry runs perform anonymous GETs only, with no submissions or mail delivery.
Schedule the command as a Hermes `--no-agent` script every 15 minutes. A file lock
prevents concurrent runs. Set `auto_apply.enabled` to `false` to stop new sends.
Existing unknown-delivery records require manual reconciliation. The mailbox
reader itself remains read-only; SMTP delivery is a separate, explicit feature.
