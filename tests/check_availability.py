"""Isolated destructive-flow and networking checks; no real sites or live data."""
import fcntl
import json
import os
import socket
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
scratch = tempfile.TemporaryDirectory(prefix="jobfind-availability-test-")
tmp = Path(scratch.name)
cfg = json.loads((ROOT / "config/example.json").read_text())
cfg["data_dir"] = str(tmp / "data")
cfg["hermes"]["output_dir"] = str(tmp / "output")
cfg["max_new_jobs_per_day"] = 100
configfile = tmp / "config.json"
configfile.write_text(json.dumps(cfg))
os.environ["JOBFIND_CONFIG"] = str(configfile)
sys.path[:0] = [str(ROOT / "scripts/modules"), str(ROOT / "hermes")]
import availability as a
import store
import context


def page(code=200, body="", error="", url="https://example.org/job/1"):
    return {"http": code, "body": body, "error": error, "final_url": url}


def seed(number):
    return {"title": "Fictional role", "company": "Demo company", "location": "Beispielstadt",
            "original_url": f"https://example.org/job/{number}", "summary": "Fictional tasks"}


class Checks(unittest.TestCase):
    def setUp(self):
        db = store.connect()
        for table in ("job_feedback", "job_likes", "jobs", "runs"):
            db.execute(f"DELETE FROM {table}")
        db.commit()
        db.close()
        marker = a.CONFIG["data_path"] / "availability-checks/last-success.json"
        marker.unlink(missing_ok=True)

    def populate(self):
        store.import_run("fictional-availability", store.now_iso(), "ok", [seed(i) for i in range(1, 4)])
        return sorted(store.list_jobs(), key=lambda j: j["original_url"])

    def test_explicit_closures(self):
        for code, text in [(410, ""), (404, "<title>Page not found</title>"),
                           (404, "Stelle nicht verfügbar"), (200, "This role has been successfully filled!"),
                           (200, "This job is no longer available and isn't accepting applications."),
                           (200, "Diese Stelle ist nicht mehr verfügbar"),
                           (200, "Das Stellenangebot steht nicht mehr zur Verfügung"),
                           (200, "<title>This Job Has Expired</title>")]:
            with self.subTest(code=code, text=text):
                self.assertEqual(a.classify(page(code, text))[0], "closed")

    def test_errors_and_ambiguous_pages_are_not_closed(self):
        for response in [page(404, ""), page(404, "Career Site"), page(403, "Forbidden"),
                         page(429), page(500), page(410, "Access denied"),
                         page(200, "Just a moment... Cloudflare"), page(None, error="request_failed"),
                         page(200, '<script>{"validThrough":"2001-01-01"}</script>'),
                         page(200, 'Report this job post is already filled'),
                         page(200, "Open job " * 300 + "This role is no longer available!")]:
            with self.subTest(response=response):
                self.assertNotEqual(a.classify(response)[0], "closed")

    def test_unsafe_urls(self):
        for url in ["file:///etc/passwd", "http://user:password@example.org/", "https://example.org:8123/", "https://example.org/\n"]:
            with self.assertRaises(ValueError):
                a.public_url(url)

    def test_private_dns_answers_and_mixed_dns_rejected(self):
        for ips in [["127.0.0.1"], ["192.168.1.1"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "10.0.0.1"]]:
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]
            with patch.object(socket, "getaddrinfo", return_value=answers), patch.object(socket, "create_connection") as open_socket:
                with self.assertRaises(ValueError):
                    a.public_socket(("example.org", 443))
                open_socket.assert_not_called()

    def test_public_dns_is_pinned(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch.object(socket, "getaddrinfo", return_value=answers), patch.object(socket, "create_connection") as connect_socket:
            a.public_socket(("example.org", 443), 12)
            connect_socket.assert_called_once_with(("93.184.216.34", 443), 12, None)

    def test_redirect_to_private_address_is_rejected(self):
        class Response:
            status = 302
            def getheader(self, key): return "http://127.0.0.1/private"
        class Connection:
            def __init__(self, host, port, timeout): self.host, self.port = host, port
            def request(self, *args, **kwargs): self._create_connection((self.host, self.port), 12)
            def getresponse(self): return Response()
            def close(self): pass
        def dns(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", port))]
        with patch.object(a.http.client, "HTTPSConnection", Connection), patch.object(a.http.client, "HTTPConnection", Connection), patch.object(socket, "getaddrinfo", side_effect=dns), patch.object(socket, "create_connection") as conn:
            self.assertEqual(a.fetch("https://example.org/job/1")["error"], "request_failed")
            self.assertEqual(conn.call_count, 1)

    def test_personio_alias_blocks_false_removal(self):
        job = {"id": "fake", "original_url": "https://fake.jobs.personio.com/job/1"}
        def fetch(url):
            return page(404, "Page not found", url=url) if ".com/" in url else page(200, "Existing job", url=url)
        self.assertEqual(a.inspect_job(job, fetch)["outcome"], "unknown")

    def test_dry_run_and_real_removal_preserve_feedback_and_likes(self):
        jobs = self.populate()
        expired, live, rejected = jobs
        store.set_user_status(expired["id"], "saved")
        store.set_job_like(expired["id"], True)
        store.delete_job(rejected["id"], ["tasks"], "Fictional feedback")
        db = store.connect()
        feedback = [tuple(r) for r in db.execute("SELECT * FROM job_feedback")]
        likes = [tuple(r) for r in db.execute("SELECT * FROM job_likes")]
        db.close()
        def fetch(url): return page(410 if url.endswith("/1") else 403, url=url)
        dry = a.run_check(dry_run=True, fetcher=fetch, pause=lambda _: None)
        self.assertEqual(dry["checked"], 2)
        self.assertEqual(dry["removed_count"], 0)
        self.assertEqual(len(store.list_jobs()), 2)
        result = a.run_check(daily=True, fetcher=fetch, pause=lambda _: None)
        self.assertEqual(result["removed"], [expired["id"]])
        self.assertEqual([j["id"] for j in store.list_jobs()], [live["id"]])
        db = store.connect()
        self.assertEqual(feedback, [tuple(r) for r in db.execute("SELECT * FROM job_feedback")])
        self.assertEqual(likes, [tuple(r) for r in db.execute("SELECT * FROM job_likes")])
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        db.close()
        with closing(__import__("sqlite3").connect(result["backup"])) as backup:
            self.assertEqual(backup.execute("SELECT user_status FROM jobs WHERE id=?", (expired["id"],)).fetchone()[0], "saved")
        self.assertNotIn(expired["original_url"], context.build_context().split('"rejections":')[1].split('"likes":')[0])
        self.assertEqual(a.run_check(daily=True, fetcher=lambda _: self.fail("daily run repeated"))["skipped"], "already_checked_today")
        store.import_run("fictional-reimport", store.now_iso(), "ok", [seed(1)])
        self.assertEqual(len(store.list_jobs()), 1)

    def test_transient_missing_page_is_kept(self):
        jobs = self.populate()
        calls = {}
        def fetch(url):
            calls[url] = calls.get(url, 0) + 1
            return page(404, "Page not found", url=url) if calls[url] == 1 else page(200, "Still here", url=url)
        result = a.run_check(fetcher=fetch, pause=lambda _: None)
        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(len(store.list_jobs()), len(jobs))

    def test_import_change_during_check_is_retained(self):
        jobs = self.populate()
        result = [{"id": jobs[0]["id"], "outcome": "closed"}]
        folder = tmp / "changed-test"
        folder.mkdir(exist_ok=True)
        db = store.connect()
        db.execute("UPDATE jobs SET last_seen_at='later' WHERE id=?", (jobs[0]["id"],))
        db.commit(); db.close()
        changed = a.apply_closed(jobs, result, folder, store.now_iso())
        self.assertEqual(changed["removed"], [])
        self.assertEqual(changed["skipped_changed"], [jobs[0]["id"]])

    def test_overlapping_run_skips(self):
        folder = a.ensure_data_dir() / "availability-checks"
        folder.mkdir(exist_ok=True)
        with (folder / "check.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(a.run_check(fetcher=lambda _: self.fail("overlapping run"))["skipped"], "already_running")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        scratch.cleanup()
