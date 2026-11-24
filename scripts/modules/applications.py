"""Application records and evidence-backed links; never changes bookmark state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timezone, timedelta
from email.utils import parseaddr
from urllib.parse import urlsplit

from config import CONFIG, ensure_data_dir
from store import connect as jobs_connect, now_iso

STATUSES = {"submitted", "reviewing", "interview", "offer", "rejected", "withdrawn"}
DATABASE = CONFIG["data_path"] / "applications.sqlite3"
GENERIC_HOSTS = {"personio.com", "personio.de", "smartrecruiters.com", "lever.co", "join.com",
    "workdayjobs.com", "myworkdayjobs.com", "recruitee.com", "softgarden.de", "concludis.de",
    "greenhouse.io", "icloud.com", "privaterelay.appleid.com", "linkedin.com", "indeed.com"}


def connect():
    ensure_data_dir()
    if not DATABASE.exists():
        try: os.close(os.open(DATABASE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError: pass
    db = sqlite3.connect(DATABASE, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS applications (
        id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
        job_id TEXT NOT NULL DEFAULT '', confirmed INTEGER NOT NULL DEFAULT 0,
        match_state TEXT NOT NULL DEFAULT 'unmatched', candidates TEXT NOT NULL DEFAULT '[]',
        manual_link INTEGER NOT NULL DEFAULT 0, override_status TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '', dismissed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT ''
      );
      CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
        message_id TEXT NOT NULL, received_at TEXT NOT NULL, status TEXT NOT NULL,
        confidence TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL,
        excerpt TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'mail'
      );
      CREATE INDEX IF NOT EXISTS events_message ON events(message_id);
      CREATE INDEX IF NOT EXISTS events_application ON events(application_id,received_at);
      CREATE TABLE IF NOT EXISTS thread_links (
        message_id TEXT NOT NULL, reference_id TEXT NOT NULL,
        application_id TEXT NOT NULL REFERENCES applications(id),
        PRIMARY KEY(message_id,reference_id)
      );
      CREATE TABLE IF NOT EXISTS mailbox_state (
        folder_key TEXT PRIMARY KEY, uidvalidity TEXT NOT NULL, high_uid INTEGER NOT NULL,
        backfill_uid INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS sync_state (
        id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL DEFAULT 'idle',
        checked_at TEXT NOT NULL DEFAULT '', last_success_at TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '', more_history INTEGER NOT NULL DEFAULT 0
      );
      INSERT OR IGNORE INTO sync_state(id) VALUES(1);
    """)
    db.commit()
    DATABASE.chmod(0o600)
    return db


def normalized(text):
    value = unicodedata.normalize("NFKD", str(text).casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def company_words(company):
    stop = {"gmbh", "co", "kg", "ag", "se", "group", "gruppe", "germany", "deutschland", "inc", "ltd", "mbh", "stuttgart", "ev"}
    company = re.sub(r"\.(?:com|de|org|net|io|co|eu)$", "", company, flags=re.I)
    return [w.replace("ae", "a").replace("oe", "o").replace("ue", "u") for w in normalized(company).split() if w not in stop and len(w) >= 3]


def same_employer(left, right):
    a, b = set(company_words(left)), set(company_words(right))
    if not a or not b: return False
    if a == b: return True
    small, large = sorted((a, b), key=len)
    generic = {"digital", "services", "software", "systems", "consulting", "solutions", "media", "studio", "design"}
    return small <= large and any(len(word) >= 4 and word not in generic for word in small)


def clean_role(title):
    title = re.split(r"\s+wurde von\s|\s+was viewed\s", title, flags=re.I)[0].strip()
    # A role must contain a recognizable occupation, not a generic sentence after 'position'.
    if not re.search(r"\b(?:UX|UI|HMI|IT|CEO|CTO|CPO)\b|design|manager|engineer|develop|entwickl|consult|berat|specialist|spezialist|owner|lead|director|head|officer|gestalt|architekt|analyst|research|referent|projekt|koordinat|sachbearbeit|leitung|mitarbeit|support|assist|redakt|kreativ|frontend|grafik|medien|senior|junior|market|sales|vertrieb|werkstudent|praktik", title, re.I): return ""
    return title


def subject_employer(subject):
    subject = re.sub(r"^(?:(?:re|aw|fw|fwd)\s*:\s*)+", "", subject, flags=re.I)
    match = re.search(r"^([^|\n]{2,80}?)\s*\|\s*(?:Deine|Ihre|Your)\s+(?:Bewerbung|application)\b", subject, re.I)
    if match and not re.search(r"bewerb|application|eingang|rückmeldung|status|danke|thank", match[1], re.I):
        return match[1].strip()
    return ""


def job_matches(message, jobs):
    subject = normalized(message["subject"])
    text = normalized(message["body"][:10000])
    sender_name, address = parseaddr(message["sender"])
    sender = normalized(sender_name + " " + address)
    sender_host = address.rsplit("@", 1)[-1].casefold()
    results = []
    explicit_employer = subject_employer(message["subject"])
    for job in jobs:
        exact = bool(job["original_url"]) and job["original_url"] in message["body"]
        # The recruiting sender/footer may belong to a shared HR provider or parent.
        # A named hiring company in the subject takes precedence over that boilerplate.
        if explicit_employer and not exact and not same_employer(explicit_employer, job["company"]): continue
        brand = " ".join(company_words(job["company"]))
        brand_present = bool(brand) and (" " + brand + " ") in (" " + subject + " " + text + " " + sender + " ")
        host = (urlsplit(job["original_url"]).hostname or "").removeprefix("www.")
        for prefix in ("careers.", "career.", "jobs.", "karriere."):
            host = host.removeprefix(prefix)
        generic = any(host == h or host.endswith("." + h) for h in GENERIC_HOSTS)
        domain = bool(host) and not generic and (sender_host == host or sender_host.endswith("." + host))
        words = [w for w in normalized(re.sub(r"\([^)]*(?:m/w|w/m|m f|m/f|all gender)[^)]*\)", "", job["title"], flags=re.I)).split()
                 if w not in {"m", "w", "d", "f", "x", "div", "all", "genders", "mwd", "mfd", "wmdd", "in", "stuttgart", "fur"} and len(w) >= 2]
        title_ratio = sum(bool(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", subject + " " + text)) for w in set(words)) / max(1, len(set(words)))
        score = (120 if exact else 0) + (40 if brand_present else 0) + (45 if domain else 0) + (45 if title_ratio >= .75 else 20 if title_ratio >= .5 else 0)
        timely = True
        if job.get("first_seen_at"):
            timely = datetime.fromisoformat(message["received_at"]) >= datetime.fromisoformat(job["first_seen_at"]) - timedelta(days=1)
        if score >= 35 and timely and (exact or brand_present or domain):
            results.append({"id": job["id"], "company": job["company"], "title": job["title"],
                "score": score, "strong": exact or ((brand_present or domain) and title_ratio >= .75)})
    results.sort(key=lambda r: (-r["score"], r["id"]))
    best = results[0] if results else None
    strong = bool(best and best["strong"] and (len(results) == 1 or best["score"] - results[1]["score"] >= 20))
    return best if strong else None, results[:5]


def inferred_identity(message, candidates):
    subject = re.sub(r"^(?:(?:re|aw|fw|fwd)\s*:\s*)+", "", message["subject"], flags=re.I)
    title = ""
    for pattern in (r"(?:bewerbung\s+als|application\s+(?:for|as)(?: the position)?|(?:für\s+die\s+|an\s+der\s+|in\s+the\s+)?(?:position|stelle)\s*[:\-]?)\s+[„\"']?(.{4,150})",
                    r"(?:bewerbung|application)\s*[:–-]\s*(.{4,150})"):
        match = re.search(pattern, subject + "\n" + message["body"][:2500], re.I)
        if match:
            title = re.split(r"\s(?:bei|at)\s|[\n|\"“]|\s/\sYour application|\sI\sEingangsbestätigung|\s[-–]\sEingangsbestätigung|\.\s", match[1], maxsplit=1, flags=re.I)[0].strip(' .„“"')
            break
    title = clean_role(title)
    company = candidates[0]["company"] if candidates else subject_employer(subject)
    if not company:
        match = re.search(r"(?:bewerbung\s+(?:bei|@)|application.{0,150}?\s(?:at|to)|(?:interview|gespräch|gespraech).{0,160}?\sbei)\s+(?:der\s+|dem\s+)?(.{2,100})", subject, re.I)
        if match: company = re.split(r"[|:]|\sauf die Position|\s[-–/]\s(?=.{0,60}(?:Designer|Manager|UX|UI|Lead|Owner))", match[1], flags=re.I)[0].strip(' .!')
    if not company:
        match = re.search(r"^(.{2,80}?)\s+[-–]\s+(?:Your|Deine|Ihre)\s+(?:Bewerbung|application)", subject, re.I)
        if match: company = match[1].strip()
    if not company:
        match = re.search(r"Gesendet im Namen von (.{2,180}?) (?:über|via) Personio", message["body"], re.I)
        if match: company = match[1].strip()
    if not company:
        name, address = parseaddr(message.get("recipient", "") if message.get("sent") else message["sender"])
        if name and (len(name.split()) == 1 or re.search(r"gmbh|company|group|\bAG\b|\bSE\b", name)) and not re.search(r"recruit|talent|bewerb|personio|smartrecruiters|no.reply|hiring team", name, re.I):
            company = name
        else:
            company = re.sub(r"\.(?:com|de|org|net|io|co|eu)$", "", address.rsplit("@", 1)[-1], flags=re.I) if "@" in address else ""
    return company[:180], title[:200]


def portal_job_ids(application, jobs, db):
    """A mailbox record belongs here only when it relates to a known portal listing."""
    by_id = {job["id"]: job for job in jobs}
    candidates = json.loads(application["candidates"]) if isinstance(application["candidates"], str) else application["candidates"]
    ids = [application["job_id"]] if application["job_id"] else [item["id"] for item in candidates]
    started = application["applied_at"] or db.execute("SELECT MIN(received_at) FROM events WHERE application_id=?", (application["id"],)).fetchone()[0]
    result = []
    for job_id in ids:
        job = by_id.get(job_id)
        if not job: continue
        first_seen = job.get("first_seen_at")
        if started and first_seen and datetime.fromisoformat(started) < datetime.fromisoformat(first_seen) - timedelta(days=1): continue
        result.append(job_id)
    return result


def ingest_message(message, classification, jobs):
    """A mail is evidence, not a command; ambiguous matches never set a job link."""
    with closing(connect()) as db, db:
        if db.execute("SELECT 1 FROM events WHERE id=?", (message["key"],)).fetchone(): return False
        app = None
        reverse = db.execute("SELECT a.* FROM thread_links t JOIN applications a ON a.id=t.application_id WHERE t.reference_id=? LIMIT 1", (message["message_id"],)).fetchone()
        if reverse: app = dict(reverse)
        for ref in message["references"]:
            if app: break
            row = db.execute("SELECT a.* FROM events e JOIN applications a ON a.id=e.application_id WHERE e.message_id=? LIMIT 1", (ref,)).fetchone()
            if row:
                app = dict(row)
                break
        if classification is None and not app: return False
        if app and not portal_job_ids(app, jobs, db): return False
        classification = classification or {"status": "message", "confidence": "high", "proof": False}
        if app and classification["status"] == "interview" and classification["confidence"] == "review":
            classification = dict(classification, confidence="high", proof=True)
        matched, candidates = job_matches(message, jobs)
        company, title = inferred_identity(message, candidates)
        if matched:
            company, title = matched["company"], matched["title"]
        if not app and matched:
            rows = db.execute("SELECT * FROM applications WHERE job_id=? ORDER BY created_at DESC", (matched["id"],)).fetchall()
            for row in rows:
                latest = db.execute("SELECT MAX(received_at) FROM events WHERE application_id=?", (row["id"],)).fetchone()[0]
                if latest and abs((datetime.fromisoformat(message["received_at"]) - datetime.fromisoformat(latest)).days) <= 180:
                    app = dict(row)
                    break
        if not app and title and company:
            rows = db.execute("SELECT * FROM applications WHERE lower(company)=lower(?) AND lower(title)=lower(?) ORDER BY created_at DESC", (company, title)).fetchall()
            for row in rows:
                latest = db.execute("SELECT MAX(received_at) FROM events WHERE application_id=?", (row["id"],)).fetchone()[0]
                if latest and abs((datetime.fromisoformat(message["received_at"]) - datetime.fromisoformat(latest)).days) <= 180:
                    app = dict(row)
                    break
        if not app and company and classification["proof"] and classification["status"] not in {"submitted", "message"}:
            # A clear follow-up can attach to one recent application at that employer.
            # This does not establish a new listing link; multiple applications stay ambiguous.
            related = []
            for row in db.execute("SELECT a.*,MAX(e.received_at) AS latest FROM applications a JOIN events e ON e.application_id=a.id WHERE a.confirmed=1 AND a.dismissed=0 GROUP BY a.id"):
                if not portal_job_ids(dict(row), jobs, db): continue
                if not same_employer(row["company"], company): continue
                if abs((datetime.fromisoformat(message["received_at"]) - datetime.fromisoformat(row["latest"])).days) > 90: continue
                left, right = set(normalized(title).split()), set(normalized(row["title"]).split())
                if left and right and len(left & right) / min(len(left), len(right)) < .5: continue
                related.append(dict(row))
            if len(related) == 1: app = related[0]
        confirmed = int(classification["proof"])
        if not app:
            if not matched and not candidates: return False
            app_id = hashlib.sha256(("application:" + message["key"]).encode()).hexdigest()[:24]
            db.execute("INSERT INTO applications(id,company,title,job_id,confirmed,match_state,candidates,created_at,applied_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (app_id, company, title, matched["id"] if matched else "", confirmed,
                 "matched" if matched else "review" if candidates else "unmatched", json.dumps(candidates), now_iso(),
                 message["received_at"] if classification["status"] == "submitted" else ""))
        else:
            app_id = app["id"]
            db.execute("UPDATE applications SET confirmed=MAX(confirmed,?) WHERE id=?", (confirmed, app_id))
            if not app["manual_link"] and not app["job_id"] and not app["title"] and title:
                db.execute("UPDATE applications SET title=? WHERE id=?", (title, app_id))
            if not app["manual_link"] and not app["job_id"] and matched:
                db.execute("UPDATE applications SET job_id=?,company=?,title=?,match_state='matched',candidates=? WHERE id=?",
                           (matched["id"], matched["company"], matched["title"], json.dumps(candidates), app_id))
            if classification["status"] == "submitted":
                db.execute("UPDATE applications SET applied_at=CASE WHEN applied_at='' OR applied_at>? THEN ? ELSE applied_at END WHERE id=?",
                           (message["received_at"], message["received_at"], app_id))
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (message["key"], app_id, message["message_id"], message["received_at"],
            classification["status"], classification["confidence"], message["subject"][:500], message["sender"][:400], message["body"][:1400], "mail"))
        for reference in message["references"]:
            db.execute("INSERT OR IGNORE INTO thread_links VALUES(?,?,?)", (message["message_id"], reference, app_id))
        return True


def effective_status(events, override=""):
    if override: return override
    meaningful = [e for e in events if e["confidence"] == "high" and e["status"] in STATUSES]
    advanced = [e for e in meaningful if e["status"] != "submitted"]
    return (advanced or meaningful)[0]["status"] if meaningful else "unknown"


def list_applications():
    with closing(jobs_connect()) as jobs_db:
        jobs = [dict(row) for row in jobs_db.execute("SELECT id,first_seen_at FROM jobs")]
    with closing(connect()) as db:
        rows = db.execute("SELECT * FROM applications WHERE dismissed=0 ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            related_ids = portal_job_ids(item, jobs, db)
            manual = db.execute("SELECT 1 FROM events WHERE application_id=? AND source='manual' LIMIT 1", (item["id"],)).fetchone()
            if not related_ids and not manual: continue
            events = [dict(e) for e in db.execute("SELECT * FROM events WHERE application_id=? ORDER BY received_at DESC,id DESC", (item["id"],))]
            item.update(status=effective_status(events, item["override_status"]), last_event_at=events[0]["received_at"] if events else item["created_at"],
                        last_subject=events[0]["subject"] if events else "", event_count=len(events), candidates=json.loads(item["candidates"]))
            item["confirmed"] = bool(item["confirmed"])
            item["candidates"] = [candidate for candidate in item["candidates"] if candidate["id"] in related_ids]
            result.append(item)
        result.sort(key=lambda a: a["last_event_at"], reverse=True)
        sync = dict(db.execute("SELECT * FROM sync_state WHERE id=1").fetchone())
        sync["enabled"] = CONFIG["applications_mail"]["enabled"]
        from auto_apply import status as automatic_status
        return {"applications": result, "sync": sync, "scope": "portal", "automation": automatic_status()}


def application_detail(app_id):
    rows = list_applications()["applications"]
    item = next((a for a in rows if a["id"] == app_id), None)
    if not item: return None
    with closing(connect()) as db:
        item["events"] = [dict(e) for e in db.execute("SELECT received_at,status,confidence,subject,sender,excerpt,source FROM events WHERE application_id=? ORDER BY received_at DESC,id DESC", (app_id,))]
    return item


def validated_update(payload):
    permitted = {"job_id", "override_status", "note", "dismissed", "confirmed", "company", "title"}
    if not isinstance(payload, dict) or set(payload) - permitted: raise ValueError("invalid_payload")
    if "override_status" in payload and payload["override_status"] not in STATUSES | {""}: raise ValueError("invalid_status")
    for key, limit in (("job_id", 20), ("company", 180), ("title", 200), ("note", 600)):
        if key in payload and (not isinstance(payload[key], str) or len(payload[key]) > limit): raise ValueError("invalid_payload")
    for key in ("dismissed", "confirmed"):
        if key in payload and type(payload[key]) is not bool: raise ValueError("invalid_payload")
    if payload.get("job_id"):
        with closing(jobs_connect()) as jobs:
            job = jobs.execute("SELECT id,title,company FROM jobs WHERE id=?", (payload["job_id"],)).fetchone()
        if not job: raise ValueError("unknown_job")
        payload = dict(payload, company=job["company"], title=job["title"])
    return payload


def update_application(app_id, payload):
    payload = validated_update(payload)
    with closing(connect()) as db, db:
        if not db.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone(): return False
        for key, value in payload.items(): db.execute(f"UPDATE applications SET {key}=? WHERE id=?", (value, app_id))
        if "job_id" in payload:
            db.execute("UPDATE applications SET manual_link=1,match_state=? WHERE id=?", ("matched" if payload["job_id"] else "unmatched", app_id))
        return True


def create_manual(payload):
    if not isinstance(payload, dict) or set(payload) - {"job_id", "company", "title", "applied_at", "note", "override_status"}: raise ValueError("invalid_payload")
    if not payload.get("job_id") and (not isinstance(payload.get("company"), str) or not payload["company"].strip()): raise ValueError("company_required")
    app_id = hashlib.sha256(os.urandom(32)).hexdigest()[:24]
    stamp = payload.get("applied_at") or now_iso()
    if not isinstance(stamp, str) or len(stamp) > 40: raise ValueError("invalid_date")
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
    stamp = parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    fields = validated_update({k: v for k, v in payload.items() if k != "applied_at"})
    with closing(connect()) as db, db:
        db.execute("INSERT INTO applications(id,company,title,confirmed,manual_link,created_at,applied_at) VALUES(?,?,?,1,1,?,?)", (app_id, "", "", now_iso(), stamp))
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", ("manual:" + app_id, app_id, "", stamp, "submitted", "high", "Manuell erfasst", "", "", "manual"))
        for key, value in fields.items(): db.execute(f"UPDATE applications SET {key}=? WHERE id=?", (value, app_id))
        db.execute("UPDATE applications SET match_state=? WHERE id=?", ("matched" if fields.get("job_id") else "unmatched", app_id))
    return app_id


def linked_jobs():
    if not DATABASE.exists(): return {}
    result = {}
    for app in list_applications()["applications"]:
        if app["confirmed"] and app["job_id"] and app["job_id"] not in result:
            result[app["job_id"]] = {"application_id": app["id"], "application_status": app["status"]}
    return result
