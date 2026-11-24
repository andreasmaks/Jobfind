"""Isolated outbox/privacy/deduplication checks; no real submissions or network."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = tempfile.TemporaryDirectory(prefix="jobfind-outbox-check-")
TEMP = Path(SCRATCH.name)
cfg = json.loads((ROOT / "config/example.json").read_text())
cfg["data_dir"] = str(TEMP / "data")
cfg["hermes"]["output_dir"] = str(TEMP / "output")
secret = TEMP / "secret"; secret.write_text("fictional-credential"); secret.chmod(0o600)
docs = {}
for lang in ("de", "en"):
    docs[lang] = {}
    for kind in ("cv", "portfolio", "combined"):
        file = TEMP / (kind + "-" + lang + ".pdf"); file.write_bytes(b"%PDF-1.4 fictional test fixture")
        docs[lang][kind] = str(file)
person = {"name": "Example Person", "email": "person@example.org", "phone": "123456",
    "address": "Example Street 1", "available_from": "2027-01-01", "salary_eur_year": 60000,
    "introduction": {"de": "Interface-Erfahrung.", "en": "Interface experience."}, "documents": docs,
    "smtp": {"host": "smtp.example.org", "port": 587, "username": "person@example.org", "credential_file": str(secret)}}
profile = TEMP / "profile.json"; profile.write_text(json.dumps(person)); profile.chmod(0o600)
cfg["auto_apply"] = {"enabled": True, "profile_file": str(profile), "routes": {}}
configuration = TEMP / "config.json"; configuration.write_text(json.dumps(cfg))
os.environ["JOBFIND_CONFIG"] = str(configuration)
sys.path.insert(0, str(ROOT / "scripts/modules"))
import auto_apply as auto
import applications
import store


class Checks(unittest.TestCase):
    def setUp(self):
        with closing(auto.connect()) as db, db:
            for table in ("application_outbox", "thread_links", "events", "applications"):
                db.execute("DELETE FROM " + table)
        with closing(store.connect()) as db, db:
            for table in ("job_feedback", "job_likes", "jobs"):
                db.execute("DELETE FROM " + table)
        self.job = {"id": "a" * 20, "canonical_key": "canonical-example", "company": "Example Services", "title": "UX Designer",
            "original_url": "https://employer.example/jobs/ux"}
        with closing(store.connect()) as db, db:
            db.execute("INSERT INTO jobs(id,canonical_key,company,title,original_url,source,first_seen_at,last_seen_at,score) VALUES(?,?,?,?,?,'example',?,?,9)",
                (*[self.job[k] for k in ("id", "canonical_key", "company", "title", "original_url")], store.now_iso(), store.now_iso()))
        self.network = patch.object(auto, "fetch", side_effect=AssertionError("unexpected network")); self.network.start()
        self.addCleanup(self.network.stop)

    def delivery(self, behavior):
        with patch.object(auto, "listing", return_value=({}, "Portfolio", "de")), patch.object(auto, "email_route", return_value="jobs@employer.example"), patch.object(auto, "send", side_effect=behavior) as send:
            result = auto.run()
        return result, send

    def test_strict_threshold_and_deletion(self):
        for score, state in ((8, "new"), (9, "deleted"), (9, "hidden"), (9, "applied")):
            with closing(store.connect()) as db, db: db.execute("UPDATE jobs SET score=?,user_status=?", (score, state))
            result, sender = self.delivery(lambda *args: self.fail("must not send"))
            self.assertEqual(result["sent"], 0); sender.assert_not_called()

    def test_confirmed_send_and_rerun(self):
        def accept(message, person, before): before()
        result, sender = self.delivery(accept)
        self.assertEqual(result["sent"], 1); sender.assert_called_once()
        self.assertEqual(applications.list_applications()["applications"][0]["status"], "submitted")
        result, sender = self.delivery(accept); sender.assert_not_called()

    def test_ambiguous_delivery_never_resends(self):
        def ambiguous(message, person, before): before(); raise OSError("private-server-error")
        result, _ = self.delivery(ambiguous)
        self.assertEqual(auto.status()["items"][0]["state"], "unknown")
        self.assertEqual(applications.list_applications()["applications"], [])
        result, sender = self.delivery(ambiguous); sender.assert_not_called()
        self.assertNotIn("private-server-error", json.dumps(auto.status()))

    def test_existing_rejected_candidate_is_skipped(self):
        app_id = applications.create_manual({"company": "Example Services", "title": "Some title", "override_status": "rejected"})
        with closing(applications.connect()) as db, db:
            db.execute("UPDATE applications SET candidates=? WHERE id=?", (json.dumps([{"id": self.job["id"]}]), app_id))
        _, sender = self.delivery(lambda *args: self.fail("duplicate application")); sender.assert_not_called()

    def test_open_portal_remains_pending(self):
        with patch.object(auto, "listing", return_value=({}, "", "en")), patch.object(auto, "send") as sender:
            result = auto.run()
        sender.assert_not_called(); self.assertEqual(result["pending"], 1)
        self.assertEqual(auto.status()["items"][0]["reason"], "portal_required")

    def test_dry_run_never_sends_or_creates_records(self):
        with patch.object(auto, "listing", return_value=({}, "", "en")), patch.object(auto, "email_route", return_value="jobs@employer.example"), patch.object(auto, "send") as sender:
            result = auto.run(dry_run=True)
        sender.assert_not_called(); self.assertEqual(result["ready"], 1)
        self.assertEqual(auto.status()["items"], [])

    def test_language_and_attachment_rules(self):
        for lang in ("de", "en"):
            for description, expected in (("CV", ["cv"]), ("Portfolio / work samples", ["cv", "portfolio"])):
                message = auto.compose(self.job, person, "jobs@employer.example", lang, description, "<example@example.org>")
                self.assertEqual([p.get_filename() for p in message.iter_attachments()], [Path(docs[lang][kind]).name for kind in expected])
                self.assertNotIn("60,000", message.get_body().get_content())
        message = auto.compose(self.job, person, "jobs@employer.example", "de", "Gehaltsvorstellung", "<example@example.org>")
        self.assertIn("60.000 Euro brutto pro Jahr", message.get_body().get_content())

    def test_private_profile_and_secret_permissions(self):
        self.assertEqual(auto.profile()["salary_eur_year"], 60000)
        secret.chmod(0o644)
        try:
            with self.assertRaises(ValueError): auto.profile()
        finally: secret.chmod(0o600)

    def test_listing_identity_language_expiry_and_redirect(self):
        payload = {"@type": "JobPosting", "title": "UX Designer", "description": "Your responsibilities and your experience. You design the product for our users with your team. " * 10}
        def response(value): return {"http": 200, "final_url": self.job["original_url"], "body": '<script type="application/ld+json">' + json.dumps(value) + '</script>', "error": ""}
        with patch.object(auto, "fetch", return_value=response(payload)): self.assertEqual(auto.listing(self.job)[2], "en")
        payload["validThrough"] = "2000-01-01"
        with patch.object(auto, "fetch", return_value=response(payload)):
            with self.assertRaises(auto.Pending): auto.listing(self.job)
        with patch.object(auto, "fetch", return_value={"http": 200, "body": "<h1>About us</h1>" + "Company text " * 100, "final_url": "https://employer.example/about", "error": ""}):
            with self.assertRaises(auto.Pending): auto.listing(self.job)

    def test_route_requires_current_evidence(self):
        route = {"url": "https://employer.example/apply", "recipient": "jobs@employer.example", "proof": "Send your application by email"}
        auto.CONFIG["auto_apply"]["routes"][self.job["id"]] = route
        try:
            for raw, expected in (("<a href='mailto:jobs@employer.example'>Send your application by email</a>", True), ("<footer><a href='mailto:support@employer.example'>Support</a></footer>", False)):
                with patch.object(auto, "fetch", return_value={"http": 200, "body": raw, "final_url": route["url"], "error": ""}):
                    if expected: self.assertEqual(auto.email_route(self.job, {}), route["recipient"])
                    else:
                        with self.assertRaises(auto.Pending): auto.email_route(self.job, {})
        finally: auto.CONFIG["auto_apply"]["routes"].clear()

    def test_smtp_marks_unknown_before_data(self):
        calls = []
        class SMTP:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def ehlo(self): pass
            def starttls(self, context): self.context = context
            def login(self, *args): pass
            def mail(self, *args): return 250, b"ok"
            def rcpt(self, *args): return 250, b"ok"
            def data(self, value): calls.append("data"); return 250, b"accepted"
        message = auto.compose(self.job, person, "jobs@employer.example", "en", "", "<example@example.org>")
        with patch.object(auto.smtplib, "SMTP", SMTP): auto.send(message, person, lambda: calls.append("durable"))
        self.assertEqual(calls, ["durable", "data"])

    def test_discovery_uses_only_structured_explicit_employer_mailbox(self):
        description = 'Bitte senden Sie Ihre Bewerbung per E-Mail an <a href="mailto:bewerbung@employer.example">bewerbung@employer.example</a>.'
        def response(text): return {"body": '<script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "description": text}) + '</script>'}
        self.assertEqual(auto.email_route(self.job, response(description)), "bewerbung@employer.example")
        for invalid in (description.replace("employer.example", "unrelated.example"), description.replace("bewerbung@", "support@"), '<a href="mailto:bewerbung@employer.example">Kontakt</a>'):
            with self.assertRaises(auto.Pending): auto.email_route(self.job, response(invalid))
        with self.assertRaises(auto.Pending): auto.email_route(self.job, {"body": description})


if __name__ == "__main__": unittest.main()
