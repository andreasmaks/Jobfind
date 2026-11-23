"""Isolated application/mail/privacy checks. No network, mailbox or production data."""
import hashlib
import http.client
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from email.message import EmailMessage
from unittest.mock import patch
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = tempfile.TemporaryDirectory(prefix="jobfind-applications-check-")
TEMP = Path(SCRATCH.name)
cfg = json.loads((ROOT / "config/example.json").read_text())
cfg["data_dir"] = str(TEMP / "data")
cfg["hermes"]["output_dir"] = str(TEMP / "output")
secret = TEMP / "mail-secret"
secret.write_text("fictional-mail-credential")
secret.chmod(0o600)
cfg["applications_mail"] = {"enabled": True, "host": "mail.example.org", "port": 993,
    "username": "owner@example.org", "credential_file": str(secret),
    "folders": [{"name": "INBOX", "sent": False}], "max_messages_per_folder": 2}
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    cfg["server"]["port"] = sock.getsockname()[1]
configuration = TEMP / "config.json"
configuration.write_text(json.dumps(cfg))
os.environ["JOBFIND_CONFIG"] = str(configuration)
sys.path[:0] = [str(ROOT / "scripts/modules"), str(ROOT / "hermes")]
import config
import store
import applications as apps
import application_mail as mail
import import_jobs

def message(subject="Your application at Example Services", body="Thanks for your application!", uid="one", **updates):
    result = {"key": hashlib.sha256(uid.encode()).hexdigest(), "message_id": f"<{uid}@example.org>", "references": [],
        "subject": subject, "body": body, "sender": "Example Services <jobs@example.org>", "sent": False,
        "received_at": "2026-11-01T10:00:00+00:00"}
    return dict(result, **updates)

def raw(uid, subject="Your application at Example Services", body="Thanks for your application!", date="Sun, 01 Nov 2026 10:00:00 +0000"):
    value = EmailMessage()
    value["Message-ID"] = f"<{uid}@example.org>"
    value["Subject"] = subject
    value["From"] = "Example Services <jobs@example.org>"
    value["Date"] = date
    value.set_content(body)
    return value.as_bytes()

class FakeIMAP:
    def __init__(self, values=None, validity=b"1", fail=False):
        self.values = values or {1: raw("one"), 2: raw("two"), 3: raw("three")}
        self.validity, self.fail, self.commands = validity, fail, []
    def login(self, user, credential):
        self.commands.append("login")
        return "OK", []
    def select(self, name, readonly=False):
        assert readonly is True
        self.commands.append(("select", name, readonly))
        return "OK", [b"3"]
    def response(self, name):
        assert name == "UIDVALIDITY"
        return name, [self.validity]
    def uid(self, command, *args):
        self.commands.append((command, args))
        if command == "search":
            values = sorted(self.values)
            if "UID 1:" in args[-1]:
                limit = int(args[-1].split(":", 1)[1].split()[0])
                values = [uid for uid in values if uid <= limit]
            return "OK", [" ".join(map(str, values)).encode()]
        assert command == "fetch"
        assert args[1].startswith("(BODY.PEEK[]<")
        if self.fail: return "NO", []
        return "OK", [(b"data", self.values[int(args[0])])]
    def logout(self): self.commands.append("logout")

class Checks(unittest.TestCase):
    def setUp(self):
        with closing(apps.connect()) as db, db:
            for name in ("thread_links", "events", "applications", "mailbox_state"):
                db.execute("DELETE FROM " + name)
            db.execute("UPDATE sync_state SET status='idle',last_success_at='',error='' WHERE id=1")
        with closing(store.connect()) as db, db:
            for name in ("job_feedback", "job_likes", "company_profiles", "company_logos", "jobs", "runs"):
                db.execute("DELETE FROM " + name)
        secret.chmod(0o600)

    def test_receipt_statuses_and_false_positives(self):
        for body, status in [("Thanks for your application!", "submitted"), ("We are reviewing your application", "reviewing"),
            ("We invite you to an interview about your application", "interview"),
            ("Here is your employment offer for your application", "offer"),
            ("Regarding your application: we are not moving forward", "rejected"),
            ("Hiermit ziehe ich meine Bewerbung zurück.", "withdrawn")]:
            self.assertEqual(mail.classify_message(message(body=body))["status"], status)
        for body in ("Newsletter: thank you for your application", "Regarding your tourist visa application", "Your betatest application was received", "Your rental application was received"):
            self.assertIsNone(mail.classify_message(message(body=body)))
        unknown = mail.classify_message(message(body="Wie geht es mit der Bewerbung weiter?"))
        self.assertFalse(unknown["proof"])
        self.assertEqual(mail.classify_message(message(body="Hiermit bewerbe ich mich als UX Designer.", sent=True))["status"], "submitted")
        self.assertFalse(mail.classify_message(message(body="Danke für deine Bewerbung.", sent=True))["proof"])

    def test_quotes_html_mime_and_dedup(self):
        decoded = mail.decode_message(raw("quoted", body="Vielen Dank für die Bewerbung, wir laden dich zum Gespräch ein.\nAm 1. Oktober schrieb Someone:\nLeider müssen wir die Bewerbung absagen."), "fallback")
        self.assertNotIn("Leider", decoded["body"])
        self.assertNotEqual(mail.classify_message(decoded)["status"], "rejected")
        value = EmailMessage()
        value["Subject"] = "Bewerbung"
        value.add_alternative('<html><head><style>danger</style></head><body><p>Danke für deine Bewerbung</p><script>bad()</script></body></html>', subtype="html")
        decoded = mail.decode_message(value.as_bytes(), "html")
        self.assertNotIn("bad()", decoded["body"])
        self.assertNotIn("danger", decoded["body"])
        self.assertTrue(apps.ingest_message(decoded, mail.classify_message(decoded), []))
        self.assertFalse(apps.ingest_message(decoded, mail.classify_message(decoded), []))
        self.assertEqual(apps.DATABASE.stat().st_mode & 0o777, 0o600)

    def test_matching_needs_employer_and_role_and_recent_listing(self):
        job = {"id": "a" * 20, "company": "Example Services GmbH", "title": "UX Product Designer", "original_url": "https://example.org/jobs/ux", "first_seen_at": "2026-10-01T00:00:00+00:00"}
        auto, suggestions = apps.job_matches(message(body="Your application at Example Services", sender="ATS <no-reply@join.com>"), [job])
        self.assertIsNone(auto)
        self.assertEqual(len(suggestions), 1)
        precise = message(body="Thanks for your application as UX Product Designer at Example Services")
        self.assertEqual(apps.job_matches(precise, [job])[0]["id"], job["id"])
        self.assertIsNone(apps.job_matches(precise, [job, dict(job, id="b" * 20)])[0])
        old = dict(precise, received_at="2021-11-01T00:00:00+00:00")
        self.assertEqual(apps.job_matches(old, [job]), (None, []))
        self.assertEqual(apps.job_matches(message(subject="Application", body="UX Product Designer", sender="ATS <no-reply@join.com>"), [job])[1], [])

    def test_reverse_threads_order_status_and_manual_override(self):
        reply = message(uid="reply", body="Regarding your application: we are not moving forward.", references=["<initial@example.org>"], received_at="2026-11-03T10:00:00+00:00")
        receipt = message(uid="initial")
        apps.ingest_message(reply, mail.classify_message(reply), [])
        apps.ingest_message(receipt, mail.classify_message(receipt), [])
        items = apps.list_applications()["applications"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "rejected")
        delayed = message(uid="delayed", references=[receipt["message_id"]], received_at="2026-11-04T10:00:00+00:00")
        apps.ingest_message(delayed, mail.classify_message(delayed), [])
        app_id = items[0]["id"]
        self.assertEqual(apps.application_detail(app_id)["status"], "rejected")
        apps.update_application(app_id, {"override_status": "interview", "note": "<script>untrusted</script>"})
        self.assertEqual(apps.application_detail(app_id)["status"], "interview")
        self.assertEqual(apps.application_detail(app_id)["note"], "<script>untrusted</script>")
        apps.update_application(app_id, {"dismissed": True})
        self.assertEqual(apps.list_applications()["applications"], [])
        self.assertFalse(apps.ingest_message(receipt, mail.classify_message(receipt), []))

    def test_manual_link_keeps_bookmark_and_deleted_job(self):
        payload = {"schema_version": 1, "run_id": "fictional-application", "run_status": "ok", "error": "", "company_profiles": [],
            "jobs": [{"title": "UX Designer", "company": "Example Services", "location": "Beispielstadt", "original_url": "https://example.org/jobs/ux", "summary": "Design", "score": 8}]}
        path = TEMP / "jobs.json"
        path.write_text(json.dumps(payload))
        import_jobs.import_file(path)
        job = store.list_jobs()[0]
        store.set_user_status(job["id"], "saved")
        app_id = apps.create_manual({"job_id": job["id"], "applied_at": "2026-11-01"})
        listed = store.list_jobs()[0]
        self.assertEqual(listed["user_status"], "saved")
        self.assertEqual(listed["application_id"], app_id)
        store.delete_job(job["id"], [], "")
        self.assertTrue(apps.update_application(app_id, {"job_id": job["id"]}))
        self.assertIsNotNone(apps.application_detail(app_id))
        self.assertEqual(store.list_jobs(), [])

    def test_manual_validation_does_not_leave_partial_records(self):
        for payload in ({}, {"company": "Example", "applied_at": "wrong"}, {"job_id": "unknown"}, {"company": 3}, {"company": "Example", "title": "x" * 201}):
            with self.assertRaises((ValueError, TypeError)): apps.create_manual(payload)
            self.assertEqual(apps.list_applications()["applications"], [])
        app_id = apps.create_manual({"company": "Example", "title": "UX"})
        with self.assertRaises(ValueError): apps.update_application(app_id, {"override_status": "invented"})
        with self.assertRaises(ValueError): apps.update_application(app_id, {"dismissed": "false"})

    def test_plain_rejection_and_unique_employer_followup(self):
        initial = message(subject="Deine Bewerbung als UX Designer / Your application as UX Designer", body="Danke für deine Bewerbung.\nGesendet im Namen von Example Services GmbH über Personio")
        apps.ingest_message(initial, mail.classify_message(initial), [])
        followup = message(uid="followup", subject="Deine Bewerbung", body="Wir haben uns entschieden, den Prozess mit anderen Bewerbenden fortzusetzen.\nGesendet im Namen von Example Services GmbH über Personio", received_at="2026-11-04T10:00:00+00:00")
        classification = mail.classify_message(followup)
        self.assertEqual(classification["status"], "rejected")
        apps.ingest_message(followup, classification, [])
        rows = apps.list_applications()["applications"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertEqual(rows[0]["title"], "UX Designer")
        self.assertEqual(rows[0]["company"], "Example Services GmbH")
        self.assertEqual(rows[0]["job_id"], "", "Employer follow-up does not invent a listing match")
        self.assertIsNone(mail.classify_message(message(subject="Interview Findings", body="Hier sind die Ergebnisse unserer Nutzerinterviews.")))
        company, title = apps.inferred_identity(message(subject="Einladung zum Gespräch für die Position UX Design Lead bei Example Services", sender="Recruiter Name <jobs@example.org>"), [])
        self.assertEqual(company, "Example Services")
        self.assertEqual(title, "UX Design Lead")
        self.assertTrue(apps.same_employer("Example Digital GmbH", "Example"))
        self.assertFalse(apps.same_employer("Digital", "Other Digital"))
        self.assertEqual(apps.clean_role("oft nur Details entscheiden und Bewerbungen abzusagen"), "")
        self.assertEqual(apps.inferred_identity(message(subject="We received your application for a position at Example Services"), [])[0], "Example Services")

    def test_two_applications_at_employer_require_followup_review(self):
        apps.create_manual({"company": "Example Services", "title": "UX Designer", "applied_at": "2026-11-01"})
        apps.create_manual({"company": "Example Services", "title": "Product Owner", "applied_at": "2026-11-02"})
        followup = message(subject="Your application at Example Services", body="We are not moving forward with your application.", received_at="2026-11-04T10:00:00+00:00")
        apps.ingest_message(followup, mail.classify_message(followup), [])
        self.assertEqual(len(apps.list_applications()["applications"]), 3, "Ambiguous follow-up is not silently assigned")

    def test_readonly_incremental_backfill_and_uidvalidity(self):
        first = FakeIMAP()
        result = mail.sync_applications(lambda: first)
        self.assertEqual(result["new_events"], 2)
        self.assertTrue(result["more_history"])
        second = FakeIMAP()
        self.assertEqual(mail.sync_applications(lambda: second)["new_events"], 1)
        third = FakeIMAP(validity=b"2")
        self.assertEqual(mail.sync_applications(lambda: third)["new_events"], 0)
        self.assertTrue(all(command == "login" or command == "logout" or command[0] in ("search", "fetch", "select") for command in first.commands))
        fourth = FakeIMAP(values={1: raw("one"), 2: raw("two"), 3: raw("three"), 4: raw("four")}, validity=b"2")
        self.assertEqual(mail.sync_applications(lambda: fourth)["new_events"], 1)

    def test_failed_fetch_retains_checkpoint_and_records(self):
        self.assertEqual(mail.sync_applications(lambda: FakeIMAP(fail=True))["status"], "error")
        with closing(apps.connect()) as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM mailbox_state").fetchone()[0], 0)
        self.assertEqual(mail.sync_applications(lambda: FakeIMAP())["status"], "ok")
        before = len(apps.list_applications()["applications"])
        secret.chmod(0o644)
        self.assertEqual(mail.sync_applications(lambda: FakeIMAP())["error"], "mail_credential_permissions")
        self.assertEqual(len(apps.list_applications()["applications"]), before)

    def test_http_auth_origin_csrf_and_no_store(self):
        spec = importlib.util.spec_from_file_location("application_test_server", ROOT / "scripts/server/server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        server.init_auth_db()
        session = server.create_session()
        httpd = server.ThreadingHTTPServer(("127.0.0.1", cfg["server"]["port"]), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        def request(method, path, payload=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", cfg["server"]["port"])
            conn.request(method, path, json.dumps(payload) if payload is not None else None, headers or {})
            response = conn.getresponse()
            result = response.status, dict(response.getheaders()), json.loads(response.read())
            conn.close()
            return result
        try:
            self.assertEqual(request("GET", "/api/applications")[0], 401)
            headers = {"Cookie": f"{server.SESSION_COOKIE}={session}", "Content-Type": "application/json"}
            self.assertEqual(request("POST", "/api/applications/manual", {"company": "Example"}, headers)[0], 403)
            headers.update({"Origin": f"http://127.0.0.1:{cfg['server']['port']}", "X-CSRF-Token": server.csrf_token(session)})
            result = request("POST", "/api/applications/manual", {"company": "Example", "title": "UX"}, headers)
            self.assertEqual(result[0], 201)
            result = request("GET", "/api/applications/" + result[2]["id"], headers=headers)
            self.assertEqual(result[0], 200)
            self.assertIn("no-store", result[1]["Cache-Control"])
            self.assertEqual(request("POST", "/api/applications/manual", {"company": "Example", "extra": True}, headers)[0], 400)
        finally:
            httpd.shutdown()
            httpd.server_close()
            server.delete_session(session)

if __name__ == "__main__":
    unittest.main(verbosity=2)
