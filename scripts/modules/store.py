"""Private SQLite storage for Hermes job results and personal decisions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from config import CONFIG, ensure_data_dir
from local_settings import decorate_job

DATA_DIR = CONFIG["data_path"]
DB_PATH = DATA_DIR / "jobs.sqlite3"
LOGO_DIR = DATA_DIR / "company-logos"
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "_ghcid", "preview_id", "pid", "display", "it", "language"}
STATUSES = {"new", "saved", "applied", "hidden"}
FEEDBACK_REASONS = {
    "field": "Fachbereich", "company": "Unternehmen", "distance": "Entfernung",
    "tasks": "Aufgaben", "hours": "Arbeitszeit", "remote": "Präsenz / Remote",
    "salary": "Gehalt", "seniority": "Erfahrungslevel", "other": "Sonstiges",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    ensure_data_dir()
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            canonical_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            original_url TEXT NOT NULL,
            source TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            remote TEXT NOT NULL DEFAULT '',
            hours TEXT NOT NULL DEFAULT '',
            employment_type TEXT NOT NULL DEFAULT '',
            posted_at TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            checked_at TEXT NOT NULL DEFAULT '',
            score INTEGER,
            summary TEXT NOT NULL DEFAULT '',
            fit TEXT NOT NULL DEFAULT '',
            concerns TEXT NOT NULL DEFAULT '',
            availability TEXT NOT NULL DEFAULT 'unknown',
            user_status TEXT NOT NULL DEFAULT 'new',
            historical INTEGER NOT NULL DEFAULT 0,
            raw_text TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_seen ON jobs(last_seen_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(user_status);
        CREATE TABLE IF NOT EXISTS job_feedback (
            job_id TEXT PRIMARY KEY REFERENCES jobs(id),
            previous_status TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            reasons TEXT NOT NULL DEFAULT '[]',
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS job_likes (
            job_id TEXT PRIMARY KEY REFERENCES jobs(id),
            liked_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            ran_at TEXT NOT NULL,
            status TEXT NOT NULL,
            imported_count INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_date ON runs(ran_at DESC);
        CREATE TABLE IF NOT EXISTS company_profiles (
            company_key TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            products TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            checked_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS company_logos (
            company_key TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            filename TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_page TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            mode TEXT NOT NULL DEFAULT 'alpha',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            checked_at TEXT NOT NULL DEFAULT ''
        );
    """)
    logo_columns = {row[1] for row in db.execute("PRAGMA table_info(company_logos)")}
    feedback_columns = {row[1] for row in db.execute("PRAGMA table_info(job_feedback)")}
    for column, default in (("reasons", "'[]'"), ("note", "''")):
        if column not in feedback_columns:
            db.execute(f"ALTER TABLE job_feedback ADD COLUMN {column} TEXT NOT NULL DEFAULT {default}")
    db.commit()
    if "mode" not in logo_columns:
        db.execute("ALTER TABLE company_logos ADD COLUMN mode TEXT NOT NULL DEFAULT 'alpha'")
        db.commit()
    DB_PATH.chmod(0o600)
    return db


def _string(value: object, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def company_key(value: object) -> str:
    return _string(value, 180).casefold()


def company_logo_path(filename: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{24}\.png", str(filename or "")):
        return None
    path = LOGO_DIR / filename
    try:
        if path.resolve().parent != LOGO_DIR.resolve():
            return None
    except OSError:
        return None
    return path


def canonical_url(value: object) -> str:
    raw = _string(value, 2000)
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
        raise ValueError("invalid_original_url")
    if parsed.username or parsed.password:
        raise ValueError("url_credentials_not_allowed")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
    host = parsed.hostname.lower()
    if host.endswith(".jobs.personio.de") or host.endswith(".jobs.personio.com"):
        query = []
    netloc = host + ((":" + str(parsed.port)) if parsed.port else "")
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip("/") or "/", urlencode(query), ""))


def normalize_job(raw: dict, *, historical: bool = False, fallback_date: str = "") -> dict:
    if not isinstance(raw, dict):
        raise ValueError("job_not_object")
    title = _string(raw.get("title"), 250)
    company = _string(raw.get("company"), 180)
    url = canonical_url(raw.get("original_url"))
    if not title or not company:
        raise ValueError("title_or_company_missing")
    source = _string(raw.get("source") or urlsplit(url).hostname, 120)
    source_id = _string(raw.get("source_id"), 200)
    key = (urlsplit(url).hostname.lower() + ":" + source_id.lower()) if source_id else url
    identifier = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    score = raw.get("score")
    if score is not None and score != "":
        try:
            score = int(score)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid_score") from error
        if not 1 <= score <= 10:
            raise ValueError("invalid_score")
    else:
        score = None
    availability = _string(raw.get("availability") or "unknown", 20)
    if availability not in {"active", "unknown", "closed"}:
        availability = "unknown"
    seen = _string(raw.get("found_at") or fallback_date or now_iso(), 40)
    return {
        "id": identifier,
        "canonical_key": key,
        "title": title,
        "company": company,
        "original_url": url,
        "source": source,
        "location": _string(raw.get("location"), 240),
        "remote": _string(raw.get("remote"), 180),
        "hours": _string(raw.get("hours"), 180),
        "employment_type": _string(raw.get("employment_type"), 120),
        "posted_at": _string(raw.get("posted_at"), 40),
        "first_seen_at": seen,
        "last_seen_at": seen,
        "checked_at": _string(raw.get("checked_at"), 40),
        "score": score,
        "summary": _string(raw.get("summary"), 2000),
        "fit": _string(raw.get("fit"), 4000),
        "concerns": _string(raw.get("concerns"), 3000),
        "availability": availability,
        "historical": 1 if historical else 0,
        "raw_text": str(raw.get("raw_text") or "")[:16000],
    }


def save_company_profiles(db: sqlite3.Connection, profiles: list[dict]) -> int:
    """Store sourced company facts only for employers already in the portal."""
    known = {company_key(row[0]) for row in db.execute("SELECT DISTINCT company FROM jobs")}
    count = 0
    for raw in profiles:
        if not isinstance(raw, dict):
            continue
        company = _string(raw.get("company"), 180)
        key = company_key(company)
        if key not in known or "nicht offengelegt" in key:
            continue
        status = raw.get("status", "ready")
        if not isinstance(status, str) or status not in {"ready", "unknown"}:
            continue
        description = _string(raw.get("description"), 1800) if isinstance(raw.get("description"), str) else ""
        products = _string(raw.get("products"), 1800) if isinstance(raw.get("products"), str) else ""
        source = ""
        if status == "ready":
            try:
                source = canonical_url(raw.get("source_url"))
            except ValueError:
                continue
            if not description or not products:
                continue
        else:
            description = products = ""
        db.execute(
            "INSERT INTO company_profiles(company_key,company,description,products,source_url,status,checked_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(company_key) DO UPDATE SET "
            "company=excluded.company,description=excluded.description,products=excluded.products,"
            "source_url=excluded.source_url,status=excluded.status,checked_at=excluded.checked_at "
            "WHERE company_profiles.status<>'ready' OR excluded.status='ready'",
            (key, company, description, products, source, status, now_iso()),
        )
        count += 1
    return count


def import_run(run_id: str, ran_at: str, status: str, jobs: list[dict], error: str = "", historical: bool = False,
               *, company_profiles: list[dict] | None = None) -> dict:
    if status not in {"ok", "empty", "error"}:
        raise ValueError("invalid_run_status")
    normalized = [normalize_job(item, historical=historical, fallback_date=ran_at) for item in jobs]
    if status != "ok" and normalized:
        raise ValueError("non_ok_run_has_jobs")
    if status == "error" and company_profiles:
        raise ValueError("error_run_has_profiles")
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            db.rollback()
            return {"already_imported": True, "count": 0}
        known_urls = {}
        known_keys = {row[0] for row in db.execute("SELECT canonical_key FROM jobs")}
        remaining = max(0, CONFIG["max_new_jobs_per_day"] - imported_today(db))
        rejected_keys = {row[0] for row in db.execute("SELECT canonical_key FROM jobs WHERE user_status='deleted'")}
        for row in db.execute("SELECT id,canonical_key,original_url,user_status FROM jobs"):
            known_urls[canonical_url(row["original_url"])] = dict(row)
        imported_count = 0
        for item in sorted(normalized, key=lambda item: item["score"] or 0, reverse=True):
            prior = known_urls.get(item["original_url"])
            if item["canonical_key"] in rejected_keys or (prior and prior.get("user_status") == "deleted"):
                continue
            if prior:
                item["id"] = prior["id"]
                item["canonical_key"] = prior["canonical_key"]
            is_new = item["canonical_key"] not in known_keys
            if is_new and imported_count >= remaining:
                continue
            columns = list(item)
            db.execute(
                f"INSERT INTO jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                "ON CONFLICT(canonical_key) DO UPDATE SET "
                "title=excluded.title, company=excluded.company, original_url=excluded.original_url, "
                "source=excluded.source, location=excluded.location, remote=excluded.remote, "
                "hours=excluded.hours, employment_type=excluded.employment_type, "
                "posted_at=excluded.posted_at, last_seen_at=MAX(jobs.last_seen_at,excluded.last_seen_at), "
                "checked_at=excluded.checked_at, score=excluded.score, summary=excluded.summary, "
                "fit=excluded.fit, concerns=excluded.concerns, availability=excluded.availability, "
                "historical=MIN(jobs.historical, excluded.historical), raw_text=excluded.raw_text",
                [item[key] for key in columns],
            )
            known_urls[item["original_url"]] = item
            known_keys.add(item["canonical_key"])
            imported_count += int(is_new)
        save_company_profiles(db, company_profiles or [])
        db.execute("INSERT INTO runs(id,ran_at,status,imported_count,error,created_at) VALUES(?,?,?,?,?,?)",
                   (run_id, ran_at, status, imported_count, _string(error, 1000), now_iso()))
        db.commit()
        return {"already_imported": False, "count": imported_count}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def imported_today(db: sqlite3.Connection) -> int:
    zone = ZoneInfo(CONFIG["timezone"])
    start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(db.execute(
        "SELECT COALESCE(SUM(imported_count),0) FROM runs WHERE created_at>=? AND created_at<?",
        (start.astimezone(timezone.utc).isoformat(timespec="seconds"),
         end.astimezone(timezone.utc).isoformat(timespec="seconds")),
    ).fetchone()[0])


def has_run(run_id: str) -> bool:
    db = connect()
    try:
        return db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is not None
    finally:
        db.close()


PUBLIC_COLUMNS = ("id", "title", "company", "original_url", "source", "location", "remote", "hours",
                  "employment_type", "posted_at", "first_seen_at", "last_seen_at", "checked_at", "score",
                  "summary", "fit", "concerns", "availability", "user_status", "historical")


def list_jobs() -> list[dict]:
    db = connect()
    try:
        rows = db.execute(f"SELECT {','.join(PUBLIC_COLUMNS)} FROM jobs WHERE user_status<>'deleted' ORDER BY first_seen_at DESC").fetchall()
        logos = {
            row["company_key"]: (row["filename"], row["mode"], re.sub(r"\D", "", row["checked_at"]))
            for row in db.execute(
                "SELECT company_key,filename,mode,checked_at FROM company_logos WHERE status='ready' AND filename<>''"
            )
            if company_logo_path(row["filename"]) and company_logo_path(row["filename"]).is_file()
        }
        result = []
        profiles = {row["company_key"]: dict(row) for row in db.execute("SELECT * FROM company_profiles")}
        liked_ids = {row[0] for row in db.execute("SELECT job_id FROM job_likes")}
        for row in rows:
            item = dict(row)
            item["liked"] = item["id"] in liked_ids
            profile = profiles.get(company_key(item["company"]), {})
            item["company_description"] = profile.get("description", "")
            item["company_products"] = profile.get("products", "")
            item["company_source_url"] = profile.get("source_url", "")
            item["company_profile_checked_at"] = profile.get("checked_at", "")
            filename, mode, version = logos.get(company_key(item["company"]), ("", "alpha", ""))
            suffix = f"?v={version}" if version else ""
            item["company_logo_url"] = f"/assets/company-logos/{filename}{suffix}" if filename else ""
            item["company_logo_mode"] = mode if mode in {"alpha", "dark", "light", "tone"} else "alpha"
            decorate_job(item)
            result.append(item)
        return result
    finally:
        db.close()


def metadata() -> dict:
    db = connect()
    try:
        counts = db.execute("SELECT COUNT(*) total, SUM(CASE WHEN user_status='new' AND historical=0 THEN 1 ELSE 0 END) new_count, "
                            "SUM(CASE WHEN user_status='saved' THEN 1 ELSE 0 END) saved_count FROM jobs WHERE user_status<>'deleted'").fetchone()
        latest = db.execute("SELECT ran_at,status,imported_count,error FROM runs ORDER BY ran_at DESC,rowid DESC LIMIT 1").fetchone()
        success = db.execute("SELECT ran_at FROM runs WHERE status IN ('ok','empty') ORDER BY ran_at DESC,rowid DESC LIMIT 1").fetchone()
        return {"total": counts["total"], "new": counts["new_count"] or 0, "saved": counts["saved_count"] or 0,
                "last_run": dict(latest) if latest else None, "last_success_at": success["ran_at"] if success else None}
    finally:
        db.close()


def set_user_status(job_id: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError("invalid_status")
    db = connect()
    try:
        result = db.execute("UPDATE jobs SET user_status=? WHERE id=? AND user_status<>'deleted'", (status, job_id))
        db.commit()
        return result.rowcount == 1
    finally:
        db.close()


def delete_job(job_id: str, reasons: list | None = None, note: str = "") -> bool:
    """Remove a job from the portal and retain it as explicit negative feedback."""
    reasons = [] if reasons is None else reasons
    if not isinstance(reasons, list) or len(reasons) > len(FEEDBACK_REASONS):
        raise ValueError("invalid_reasons")
    if any(not isinstance(reason, str) or reason not in FEEDBACK_REASONS for reason in reasons):
        raise ValueError("invalid_reasons")
    if not isinstance(note, str) or len(note) > 600:
        raise ValueError("invalid_note")
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT user_status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return False
        if row["user_status"] != "deleted":
            db.execute("INSERT INTO job_feedback(job_id,previous_status,deleted_at,reasons,note) VALUES(?,?,?,?,?)",
                       (job_id, row["user_status"], now_iso(), json.dumps(list(dict.fromkeys(reasons))), note.strip()))
            db.execute("UPDATE jobs SET user_status='deleted' WHERE id=?", (job_id,))
        db.commit()
        return True
    finally:
        db.close()


def restore_job(job_id: str) -> bool:
    """Undo deletion, including its recommendation feedback and saved status."""
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT previous_status FROM job_feedback WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return db.execute("SELECT 1 FROM jobs WHERE id=? AND user_status<>'deleted'", (job_id,)).fetchone() is not None
        db.execute("UPDATE jobs SET user_status=? WHERE id=?", (row[0], job_id))
        db.execute("DELETE FROM job_feedback WHERE job_id=?", (job_id,))
        db.commit()
        return True
    finally:
        db.close()


def set_job_like(job_id: str, liked: bool) -> bool:
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM jobs WHERE id=? AND user_status<>'deleted'", (job_id,)).fetchone():
            return False
        if liked:
            db.execute("INSERT OR IGNORE INTO job_likes(job_id,liked_at) VALUES(?,?)", (job_id, now_iso()))
        else:
            db.execute("DELETE FROM job_likes WHERE job_id=?", (job_id,))
        db.commit()
        return True
    finally:
        db.close()
