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
import auto_apply

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


def bounce(uid="bounce-one", action="failed", status="5.7.1", recipient="jobs@example.org", original="<outgoing@example.org>"):
    return (f"From: Mail Delivery System <mailer-daemon@provider.example>\n"
        f"To: owner@example.org\nSubject: Undelivered Mail Returned to Sender\nMessage-ID: <{uid}@provider.example>\n"
        "Date: Tue, 24 Nov 2026 07:22:00 +0000\nMIME-Version: 1.0\nContent-Type: multipart/report; report-type=delivery-status; boundary=dsn\n\n"
        "--dsn\nContent-Type: text/plain\n\nYour email could not be delivered.\n"
        "--dsn\nContent-Type: message/delivery-status\n\nReporting-MTA: dns; outbound.provider.example\n\n"
        f"Original-Recipient: rfc822;{recipient}\nFinal-Recipient: rfc822;masked@masked.example\nAction: {action}\nStatus: {status}\n"
        "Diagnostic-Code: smtp; 550 5.7.1 [CS101] Message rejected due to local policy\n\n"
        "--dsn\nContent-Type: text/rfc822-headers\n\n"
        f"Message-ID: {original}\nSubject: Bewerbung UX Designer\nTo: {recipient}\n\n--dsn--\n").encode()

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
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='application_outbox'").fetchone(): db.execute("DELETE FROM application_outbox")
            for name in ("thread_links", "events", "applications", "mailbox_state"):
                db.execute("DELETE FROM " + name)
            db.execute("UPDATE sync_state SET status='idle',last_success_at='',error='' WHERE id=1")
        with closing(store.connect()) as db, db:
            for name in ("job_feedback", "job_likes", "company_profiles", "company_logos", "jobs", "runs"):
                db.execute("DELETE FROM " + name)
        secret.chmod(0o600)
        payload = {"schema_version": 1, "run_id": "portal-fixture", "run_status": "ok", "error": "", "company_profiles": [],
            "jobs": [{"title": "UX Designer", "company": "Example Services", "location": "Beispielstadt", "original_url": "https://example.org/jobs/ux", "summary": "Design", "score": 8}]}
        path = TEMP / "portal.json"
        path.write_text(json.dumps(payload))
        import_jobs.import_file(path)
        with closing(store.connect()) as db, db:
            db.execute("UPDATE jobs SET first_seen_at='2026-10-01T00:00:00+00:00'")
            self.jobs = [dict(row) for row in db.execute("SELECT id,company,title,original_url,first_seen_at FROM jobs")]

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

    def prepare_outgoing(self):
        job = store.list_jobs()[0]
        store.set_user_status(job["id"], "saved")
        app_id = auto_apply.record_sent(job, "<outgoing@example.org>", "2026-11-24T07:21:00+00:00")
        with closing(auto_apply.connect()) as db, db:
            db.execute("INSERT INTO application_outbox(job_id,fingerprint,company,title,state,recipient,message_id,created_at,checked_at,sent_at) VALUES(?,?,?,?,'sent',?,?,?, ?,?)", (job["id"], "fictional-fingerprint", job["company"], job["title"], "jobs@example.org", "<outgoing@example.org>", "2026-11-24T07:21:00+00:00", "2026-11-24T07:21:00+00:00", "2026-11-24T07:21:00+00:00"))
        return app_id

    def test_permanent_dsn_is_not_a_hiring_rejection(self):
        app_id = self.prepare_outgoing()
        decoded = mail.decode_message(bounce(), "fallback")
        self.assertTrue(decoded["delivery_report"])
        self.assertEqual(decoded["delivery_failures"][0]["original_message_id"], "<outgoing@example.org>")
        self.assertTrue(apps.ingest_message(decoded, mail.classify_message(decoded), self.jobs))
        detail = apps.application_detail(app_id)
        self.assertEqual(detail["status"], "delivery_failed")
        self.assertIn("CS101", detail["events"][0]["excerpt"])
        self.assertEqual(store.list_jobs()[0]["application_status"], "delivery_failed")
        self.assertEqual(store.list_jobs()[0]["user_status"], "saved")
        self.assertEqual(auto_apply.status()["items"][0]["state"], "failed")
        self.assertFalse(apps.ingest_message(decoded, mail.classify_message(decoded), self.jobs))
        # A later real employer receipt recovers the initial submission state.
        receipt = message(uid="later-receipt", subject="Your application at Example Services", body="Thanks for your application!", received_at="2026-11-24T08:00:00+00:00", references=["<outgoing@example.org>"])
        apps.ingest_message(receipt, mail.classify_message(receipt), self.jobs)
        self.assertEqual(apps.application_detail(app_id)["status"], "submitted")

    def test_delay_or_unmatched_dsn_does_not_change_application(self):
        app_id = self.prepare_outgoing()
        for changes in ({"recipient": "other@example.org"}, {"original": "<other@example.org>"}, {"action": "delayed", "status": "4.2.0"}):
            decoded = mail.decode_message(bounce(**changes), "fallback")
            self.assertFalse(apps.ingest_message(decoded, mail.classify_message(decoded), self.jobs))
            self.assertEqual(apps.application_detail(app_id)["status"], "submitted")
        self.assertEqual(auto_apply.status()["items"][0]["state"], "sent")

    def test_plain_provider_bounce_and_recent_backfill(self):
        app_id = self.prepare_outgoing()
        body = "This is a system-generated message. Your email could not be delivered.\nOriginal-Recipient: rfc822;jobs@example.org\nAction: failed\nStatus: 5.7.1\nDiagnostic-Code: smtp; 550 [CS101] local policy\nMessage-ID: <outgoing@example.org>\n"
        decoded = mail.decode_message(raw("plain-bounce", subject="Undelivered mail", body=body, date="Tue, 24 Nov 2026 07:22:00 +0000"), "fallback")
        self.assertEqual(mail.classify_message(decoded)["status"], "delivery_failed")
        # Simulate the old recognizer having advanced its UID checkpoint already.
        fake = FakeIMAP(values={1: bounce()})
        key = hashlib.sha256((cfg["applications_mail"]["host"] + "|" + cfg["applications_mail"]["username"] + "|INBOX").encode()).hexdigest()
        with closing(apps.connect()) as db, db: db.execute("INSERT INTO mailbox_state VALUES(?,?,?,?)", (key, "1", 1, 0))
        self.assertEqual(mail.sync_applications(lambda: fake)["new_events"], 1)
        self.assertEqual(apps.application_detail(app_id)["status"], "delivery_failed")
        self.assertTrue(any(command[0] == "search" and "SINCE " in command[1][-1] for command in fake.commands if isinstance(command, tuple)))

    def test_quotes_html_mime_and_dedup(self):
        decoded = mail.decode_message(raw("quoted", body="Vielen Dank für die Bewerbung, wir laden dich zum Gespräch ein.\nAm 1. Oktober schrieb Someone:\nLeider müssen wir die Bewerbung absagen."), "fallback")
        self.assertNotIn("Leider", decoded["body"])
        self.assertNotEqual(mail.classify_message(decoded)["status"], "rejected")
        value = EmailMessage()
        value["Subject"] = "Bewerbung"
        value["From"] = "Example Services <jobs@example.org>"
        value.add_alternative('<html><head><style>danger</style></head><body><p>Danke für deine Bewerbung</p><script>bad()</script></body></html>', subtype="html")
        decoded = mail.decode_message(value.as_bytes(), "html")
        self.assertNotIn("bad()", decoded["body"])
        self.assertNotIn("danger", decoded["body"])
        self.assertTrue(apps.ingest_message(decoded, mail.classify_message(decoded), self.jobs))
        self.assertFalse(apps.ingest_message(decoded, mail.classify_message(decoded), self.jobs))
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
        apps.ingest_message(reply, mail.classify_message(reply), self.jobs)
        apps.ingest_message(receipt, mail.classify_message(receipt), self.jobs)
        items = apps.list_applications()["applications"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "rejected")
        delayed = message(uid="delayed", references=[receipt["message_id"]], received_at="2026-11-04T10:00:00+00:00")
        apps.ingest_message(delayed, mail.classify_message(delayed), self.jobs)
        app_id = items[0]["id"]
        self.assertEqual(apps.application_detail(app_id)["status"], "rejected")
        apps.update_application(app_id, {"override_status": "interview", "note": "<script>untrusted</script>"})
        self.assertEqual(apps.application_detail(app_id)["status"], "interview")
        self.assertEqual(apps.application_detail(app_id)["note"], "<script>untrusted</script>")
        apps.update_application(app_id, {"dismissed": True})
        self.assertEqual(apps.list_applications()["applications"], [])
        self.assertFalse(apps.ingest_message(receipt, mail.classify_message(receipt), self.jobs))

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
        jobs = [dict(self.jobs[0], title="Senior UX Interaction Designer")]
        initial = message(subject="Deine Bewerbung als UX Designer / Your application as UX Designer", body="Danke für deine Bewerbung.\nGesendet im Namen von Example Services GmbH über Personio")
        apps.ingest_message(initial, mail.classify_message(initial), jobs)
        followup = message(uid="followup", subject="Deine Bewerbung", body="Wir haben uns entschieden, den Prozess mit anderen Bewerbenden fortzusetzen.\nGesendet im Namen von Example Services GmbH über Personio", received_at="2026-11-04T10:00:00+00:00")
        classification = mail.classify_message(followup)
        self.assertEqual(classification["status"], "rejected")
        apps.ingest_message(followup, classification, jobs)
        rows = apps.list_applications()["applications"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertEqual(rows[0]["title"], "UX Designer")
        self.assertEqual(rows[0]["company"], "Example Services")
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
        apps.ingest_message(followup, mail.classify_message(followup), self.jobs)
        self.assertEqual(len(apps.list_applications()["applications"]), 3, "Ambiguous follow-up is not silently assigned")

    def test_unrelated_and_pre_portal_mail_is_ignored(self):
        unrelated = message(subject="Your application at Other Employer", sender="Other Employer <hr@other.example>", body="Thanks for your application!", uid="outside")
        self.assertFalse(apps.ingest_message(unrelated, mail.classify_message(unrelated), self.jobs))
        old = message(uid="old", received_at="2021-01-01T00:00:00+00:00", body="Thanks for your application as UX Designer at Example Services.")
        self.assertFalse(apps.ingest_message(old, mail.classify_message(old), self.jobs))
        self.assertEqual(apps.list_applications()["applications"], [])
        # Existing imported history is hidden from list and detail, including old roles
        # at an employer that has a different, newly listed job in the portal.
        current = message(body="Thanks for your application as UX Designer at Example Services.")
        self.assertTrue(apps.ingest_message(current, mail.classify_message(current), self.jobs))
        record = apps.list_applications()["applications"][0]
        with closing(apps.connect()) as db, db:
            db.execute("UPDATE applications SET applied_at='2021-01-01T00:00:00+00:00' WHERE id=?", (record["id"],))
        self.assertEqual(apps.list_applications()["applications"], [])
        self.assertIsNone(apps.application_detail(record["id"]))
        followup = message(uid="old-followup", references=[current["message_id"]], body="We are not moving forward with your application.")
        self.assertFalse(apps.ingest_message(followup, mail.classify_message(followup), self.jobs))
        self.assertEqual(apps.list_applications()["scope"], "portal")

    def test_hiring_company_precedes_shared_recruiting_sender_and_footer(self):
        message_data = message(subject="Child Company | Deine Bewerbung", sender="Recruiter <career@parent.example>",
            body="Deine Bewerbung als UX Designer bei Child Company können wir leider nicht weiter berücksichtigen. Gesendet im Namen von Parent Digital GmbH über Personio")
        company, title = apps.inferred_identity(message_data, [])
        self.assertEqual(company, "Child Company")
        self.assertEqual(title, "UX Designer")
        child = dict(self.jobs[0], company="Child Company GmbH", original_url="https://child.jobs.personio.com/job/1")
        parent = dict(child, id="p" * 20, company="Parent Digital GmbH", original_url="https://parent.jobs.personio.com/job/2")
        matched, candidates = apps.job_matches(message_data, [parent, child])
        self.assertEqual(matched["id"], child["id"])
        self.assertEqual([candidate["id"] for candidate in candidates], [child["id"]])
        self.assertEqual(mail.classify_message(message_data)["status"], "rejected")
        reply = dict(message_data, subject="AW: Child Company | Deine Bewerbung")
        self.assertEqual(apps.inferred_identity(reply, [])[0], "Child Company")

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
            raw_body = response.read()
            result = response.status, dict(response.getheaders()), raw_body if response.getheader("Content-Type") == "application/pdf" else json.loads(raw_body)
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
            rejected = {"id": "rejected", "user_status": "saved", "application_status": "rejected"}
            available = {"id": "available", "user_status": "saved", "application_status": "reviewing"}
            with patch.object(server, "list_jobs", return_value=[rejected, available]), patch("pdf_export.build_pdf", return_value=b"%PDF-fixture") as build:
                self.assertEqual(request("POST", "/api/export/saved.pdf", {"language": "de"}, headers)[0], 200)
                self.assertEqual(build.call_args.args[0], [available], "Rejected listings are not sent to the PDF builder")
            with patch.object(server, "list_jobs", return_value=[rejected]), patch("pdf_export.build_pdf") as build:
                self.assertEqual(request("POST", "/api/export/saved.pdf", {"language": "de"}, headers)[0], 400)
                build.assert_not_called()
        finally:
            httpd.shutdown()
            httpd.server_close()
            server.delete_session(session)

    def test_rejection_keeps_application_details_and_bookmark(self):
        job = store.list_jobs()[0]
        store.set_user_status(job["id"], "saved")
        app_id = apps.create_manual({"job_id": job["id"], "override_status": "rejected"})
        listed = store.list_jobs()[0]
        self.assertEqual(listed["application_status"], "rejected")
        self.assertEqual(listed["user_status"], "saved")
        self.assertEqual(apps.application_detail(app_id)["status"], "rejected")
        with closing(store.connect()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM job_feedback").fetchone()[0], 0)
        apps.update_application(app_id, {"override_status": "reviewing"})
        self.assertEqual(store.list_jobs()[0]["application_status"], "reviewing")

if __name__ == "__main__":
    unittest.main(verbosity=2)
