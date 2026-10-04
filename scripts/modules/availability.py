"""Conservative, model-free checks of existing listings; never rejection feedback."""
from __future__ import annotations

import collections
import concurrent.futures
from contextlib import closing
import fcntl
import html
import http.client
import ipaddress
import json
import re
import socket
import sqlite3
import threading
import time
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from config import CONFIG, ensure_data_dir
from store import connect

MAX_BODY = 2_000_000
BLOCKED = re.compile(r"captcha|cloudflare|verify you are human|access denied|just a moment|"
                     r"security check|unusual traffic|authenticating|temporarily unavailable|"
                     r"service unavailable|wartungsarbeiten", re.I)
CLOSED = re.compile(r"this (?:job|role|position)(?: posting)? (?:is no longer (?:available|active|accepting)|"
                    r"has expired|has been (?:successfully filled|closed|filled))|"
                    r"(?:diese|die) (?:stelle|stellenanzeige|ausschreibung) (?:ist|wurde) "
                    r"(?:leider )?(?:nicht mehr verfügbar|bereits besetzt|abgelaufen|geschlossen)|"
                    r"stellenausschreibung beendet|stelle nicht verfügbar|"
                    r"(?:stellenangebot|angebot) (?:steht |ist )(?:leider )?(?:nicht mehr zur verfügung|abgelaufen)|"
                    r"diese stelle lässt keine bewerbungen mehr zu", re.I)
MISSING = re.compile(r"page not found|seite (?:wurde )?nicht gefunden|job posting not found|"
                     r"stellenangebot gibt es nicht|stellenangebot ist nicht mehr aktuell|"
                     r"stelle nicht verfügbar", re.I)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def public_url(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or any(c.isspace() or ord(c) < 32 for c in url)):
        raise ValueError("unsafe_url")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("unsafe_port")
    return parsed.scheme, parsed.hostname.encode("idna").decode("ascii"), port


def public_socket(address, timeout=12, source_address=None):
    """Validate every DNS answer and pin the connection to a public address."""
    host, port = address
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers or any(not ipaddress.ip_address(a[4][0]).is_global for a in answers):
        raise ValueError("non_public_address")
    last = None
    for answer in answers:
        try:
            return socket.create_connection((answer[4][0], port), timeout, source_address)
        except OSError as error:
            last = error
    raise last or OSError("connection_failed")


def fetch(url: str) -> dict:
    """Only anonymous GETs, bounded bodies/timeouts and validated redirects."""
    current = url
    try:
        for _ in range(5):
            scheme, host, port = public_url(current)
            parsed = urlsplit(current)
            connection_type = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            connection = connection_type(host, port, timeout=12)
            connection._create_connection = public_socket
            try:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                connection.request("GET", path, headers={"User-Agent": "Mozilla/5.0 (compatible; Jobfind availability check)",
                                   "Accept": "text/html,application/json", "Accept-Language": "de,en;q=0.8",
                                   "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise ValueError("redirect_without_location")
                    current = urljoin(current, location)
                    continue
                body = response.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    return {"http": response.status, "final_url": current, "body": "", "error": "body_limit"}
                return {"http": response.status, "final_url": current,
                        "body": body.decode("utf-8", errors="replace"), "error": ""}
            finally:
                connection.close()
        raise ValueError("redirect_limit")
    except (OSError, ValueError, http.client.HTTPException):
        # Never expose arbitrary remote errors or page text in service logs.
        return {"http": None, "final_url": current, "body": "", "error": "request_failed"}


def classify(response: dict) -> tuple[str, str]:
    if response.get("error"):
        return "unknown", response["error"]
    raw = response.get("body", "")
    parser = PageText()
    parser.feed(raw)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    heading = html.unescape(title[1]) if title else ""
    # Restrict notices to the page heading/start, not related jobs or report dialogs.
    intro = heading + " " + text[:2000]
    if BLOCKED.search(intro):
        return "unknown", "blocked_or_temporary"
    code = response.get("http")
    if code == 410:
        return "closed", "http_410"
    if code == 404 and (MISSING.search(intro) or CLOSED.search(intro)):
        return "closed", "http_404_missing_listing"
    if code == 200 and CLOSED.search(intro):
        return "closed", "explicit_closure_notice"
    if code == 200 and (re.search(r'"@type"\s*:\s*"JobPosting"', raw) or len(text) > 800):
        return "present", "page_reachable_not_proof_of_opening"
    return "unknown", "inconclusive"


def inspect_job(job: dict, fetcher=fetch) -> dict:
    response = fetcher(job["original_url"])
    outcome, reason = classify(response)
    # Personio's .com/.de aliases sometimes differ; an existing alternate prevents removal.
    if outcome == "closed" and ".jobs.personio.com/" in job["original_url"]:
        alternate = fetcher(job["original_url"].replace(".jobs.personio.com/", ".jobs.personio.de/"))
        if classify(alternate)[0] != "closed":
            outcome, reason = "unknown", "personio_alias_not_confirmed_closed"
    return {"id": job["id"], "original_url": job["original_url"], "http": response.get("http"),
            "final_url": response.get("final_url", ""), "outcome": outcome, "reason": reason}


def write_report(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    temporary.chmod(0o600)
    temporary.replace(path)


def apply_closed(jobs: list[dict], results: list[dict], folder: Path, stamp: str) -> dict:
    """Tombstones prevent reimport. No job_feedback or job_likes changes."""
    by_id = {job["id"]: job for job in jobs}
    candidates = [r for r in results if r["outcome"] == "closed"]
    if not candidates:
        return {"removed": [], "skipped_changed": [], "backup": ""}
    backup = folder / "before-cleanup.sqlite3"
    db = connect()
    try:
        with closing(sqlite3.connect(backup)) as destination:
            db.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup_integrity_failed")
        backup.chmod(0o600)
        db.execute("BEGIN IMMEDIATE")
        removed, skipped = [], []
        for result in candidates:
            expected = by_id[result["id"]]
            row = db.execute("SELECT * FROM jobs WHERE id=?", (result["id"],)).fetchone()
            if (not row or row["user_status"] == "deleted" or row["original_url"] != expected["original_url"]
                    or row["last_seen_at"] != expected["last_seen_at"]):
                skipped.append(result["id"])
                continue
            removed.append({"before": dict(row), "evidence": result})
            db.execute("UPDATE jobs SET user_status='deleted', availability='closed', checked_at=? WHERE id=?",
                       (stamp, result["id"]))
        # Persist recovery information before committing destructive visibility changes.
        write_report(folder / "removed-jobs.json", {"checked_at": stamp, "jobs": removed})
        db.commit()
        return {"removed": [r["before"]["id"] for r in removed], "skipped_changed": skipped, "backup": str(backup)}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def run_check(*, dry_run: bool = False, daily: bool = False, fetcher=fetch, pause=time.sleep) -> dict:
    folder = ensure_data_dir() / "availability-checks"
    folder.mkdir(mode=0o700, exist_ok=True)
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo(CONFIG["timezone"])).date().isoformat()
    with (folder / "check.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": True, "skipped": "already_running"}
        latest = folder / "last-success.json"
        if daily and not dry_run and latest.exists() and json.loads(latest.read_text()).get("day") == day:
            return {"ok": True, "skipped": "already_checked_today"}
        db = connect()
        try:
            jobs = [dict(row) for row in db.execute("SELECT id,original_url,last_seen_at FROM jobs WHERE user_status<>'deleted'")]
        finally:
            db.close()
        semaphores = collections.defaultdict(lambda: threading.Semaphore(2))

        def check(job):
            with semaphores[urlsplit(job["original_url"]).hostname]:
                return inspect_job(job, fetcher)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(check, jobs))
            candidates = [job for job, result in zip(jobs, results) if result["outcome"] == "closed"]
            if candidates:
                pause(2)
                repeated = {r["id"]: r for r in pool.map(check, candidates)}
                for result in results:
                    if result["id"] in repeated:
                        result["confirmation"] = repeated[result["id"]]
                        if (repeated[result["id"]]["outcome"] != "closed"
                                or repeated[result["id"]]["reason"] != result["reason"]
                                or repeated[result["id"]]["final_url"] != result["final_url"]):
                            result["outcome"], result["reason"] = "unknown", "closure_not_confirmed"
        run = Path(tempfile.mkdtemp(prefix=now.strftime("%Y%m%dT%H%M%S") + "-", dir=folder))
        result = {"ok": True, "checked_at": now.isoformat(timespec="seconds"), "day": day,
                  "dry_run": dry_run, "checked": len(jobs), "outcomes": dict(collections.Counter(r["outcome"] for r in results)),
                  "results": results, "removed": [], "skipped_changed": [], "backup": ""}
        write_report(run / "report.json", result)
        if not dry_run:
            result.update(apply_closed(jobs, results, run, result["checked_at"]))
            write_report(run / "report.json", result)
            write_report(latest, {"day": day, "report": str(run / "report.json")})
        return {k: v for k, v in result.items() if k != "results"} | {"removed_count": len(result["removed"]), "report": str(run / "report.json")}
