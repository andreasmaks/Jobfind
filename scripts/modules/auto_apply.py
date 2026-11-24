"""Private, durable application outbox. Only verified email routes are sent unattended.

Portal workflows stay pending rather than inventing answers, creating accounts or
claiming delivery. No language model and no Codex quota are used.
"""
from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
from contextlib import closing
from datetime import date
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from config import CONFIG, ROOT, ensure_data_dir
from store import connect as jobs_connect, now_iso
import applications
from availability import fetch, classify


class Pending(Exception):
    pass


def private_json(path):
    path = Path(path).expanduser().resolve()
    if path.is_relative_to(ROOT) or path.stat().st_mode & 0o077:
        raise ValueError("private_profile_permissions")
    return json.loads(path.read_text())


def profile():
    value = private_json(CONFIG["auto_apply"]["profile_file"])
    for key in ("name", "email", "phone", "address", "available_from"):
        if not isinstance(value.get(key), str) or not value[key].strip() or any(c in value[key] for c in "\r\n\x00"):
            raise ValueError("invalid_application_profile")
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value["email"]):
        raise ValueError("invalid_sender")
    date.fromisoformat(value["available_from"])
    if type(value.get("salary_eur_year")) is not int or not 1000 <= value["salary_eur_year"] <= 1000000:
        raise ValueError("invalid_salary")
    for language in ("de", "en"):
        for kind in ("cv", "portfolio", "combined"):
            path = Path(value["documents"][language][kind]).expanduser().resolve()
            if path.is_relative_to(ROOT) or path.suffix.lower() != ".pdf" or not path.is_file():
                raise ValueError("invalid_document")
            with path.open("rb") as handle: header = handle.read(5)
            if not 10 <= path.stat().st_size <= 20000000 or header != b"%PDF-":
                raise ValueError("invalid_pdf")
            value["documents"][language][kind] = str(path)
    smtp = value["smtp"]
    if type(smtp["port"]) is not int or not 1 <= smtp["port"] <= 65535:
        raise ValueError("invalid_smtp")
    secret = Path(smtp["credential_file"]).expanduser().resolve()
    if secret.is_relative_to(ROOT) or secret.stat().st_mode & 0o077:
        raise ValueError("private_credential_permissions")
    return value


def connect():
    db = applications.connect()
    db.execute("""CREATE TABLE IF NOT EXISTS application_outbox (
      job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
      company TEXT NOT NULL, title TEXT NOT NULL, state TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT '', recipient TEXT NOT NULL DEFAULT '',
      language TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, checked_at TEXT NOT NULL, sent_at TEXT NOT NULL DEFAULT '',
      application_id TEXT NOT NULL DEFAULT ''
    )""")
    db.commit()
    return db


def status():
    enabled = CONFIG["auto_apply"]["enabled"]
    if not applications.DATABASE.exists(): return {"enabled": enabled, "items": []}
    with closing(connect()) as db:
        items = [dict(row) for row in db.execute("SELECT job_id,company,title,state,reason,checked_at FROM application_outbox ORDER BY checked_at DESC")]
    return {"enabled": enabled, "items": items}


def already_applied(job):
    """Keep ignored/closed records for deduplication, including unconfirmed links."""
    with closing(applications.connect()) as db:
        for row in db.execute("SELECT * FROM applications"):
            candidates = json.loads(row["candidates"])
            if row["job_id"] == job["id"] or any(c.get("id") == job["id"] for c in candidates): return True
            if (applications.same_employer(row["company"], job["company"])
                    and applications.normalized(row["title"]) == applications.normalized(job["title"])): return True
    return False


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.active = [], None
    def handle_starttag(self, tag, attrs):
        if tag == "a": self.active = [dict(attrs).get("href", ""), ""]
    def handle_data(self, data):
        if self.active is not None: self.active[1] += data
    def handle_endtag(self, tag):
        if tag == "a" and self.active is not None:
            self.links.append(tuple(self.active)); self.active = None


def postings(raw):
    result = []
    def visit(item):
        if isinstance(item, list):
            for child in item: visit(child)
        elif isinstance(item, dict):
            if item.get("@type") == "JobPosting" or "JobPosting" in (item.get("@type") if isinstance(item.get("@type"), list) else []): result.append(item)
            if "@graph" in item: visit(item["@graph"])
    for block in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try: visit(json.loads(block))
        except (ValueError, TypeError): pass
    return result


def listing(job):
    response = fetch(job["original_url"])
    state, _ = classify(response)
    if state != "present" or response.get("http") != 200: raise Pending("listing_unverified")
    raw = response["body"]
    normalized = applications.normalized
    role = normalized(job["title"])
    words = [w for w in role.split() if len(w) > 2 and w not in {"stuttgart", "senior", "designerin"}]
    candidates = postings(raw)
    posting = next((p for p in candidates if sum(w in normalized(p.get("title", "")) for w in words) >= max(1, len(words) * .7)), None)
    # A redirect to a corporate homepage is not proof that this job is open.
    title_heading = " ".join(re.findall(r'<(?:h1|title)\b[^>]*>(.*?)</(?:h1|title)>', raw, re.S | re.I))
    if not posting and sum(w in normalized(title_heading) for w in words) < max(1, len(words) * .7): raise Pending("listing_unverified")
    if posting:
        expires = str(posting.get("validThrough", ""))[:10]
        if expires:
            try:
                if date.fromisoformat(expires) < date.today(): raise Pending("listing_expired")
            except ValueError: pass
    description = html.unescape(re.sub(r"<[^>]+>", " ", str(posting.get("description", "")) if posting else raw))
    # Inspect the actual listing text, not just the locale in the URL.
    declared = str((posting or {}).get("inLanguage", "")).lower()
    english = len(re.findall(r"\b(?:you|your|our|the|experience|responsibilities|requirements)\b", description, re.I))
    german = len(re.findall(r"\b(?:Sie|Ihre|wir|und|Erfahrung|Aufgaben|Profil)\b", description, re.I))
    language = "en" if declared.startswith("en") or (english >= 8 and english > german * 1.5) else "de"
    return response, description, language


def email_route(job, response):
    """Owner-reviewed routes must still be present on the current employer page.

    Never turn footer, support, privacy or named recruiting contacts into an
    application address. New portal types need a dedicated, reviewed adapter.
    """
    route = CONFIG["auto_apply"].get("routes", {}).get(job["id"])
    if not route:
        # Automatic discovery is restricted to the structured job description,
        # explicit application wording and a mailbox on the employer's domain.
        # Shared ATS domains and generic page/footer mailboxes cannot pass.
        host = (urlsplit(job["original_url"]).hostname or "").removeprefix("www.")
        found = set()
        for posting in postings(response.get("body", "")):
            description = str(posting.get("description", ""))
            links = Links(); links.feed(description)
            plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description)))
            for href, label in links.links:
                if not href.lower().startswith("mailto:"): continue
                address = unquote(href[7:].split("?", 1)[0]).casefold()
                if not re.fullmatch(r"(?:bewerbung(?:en)?|jobs|careers|applications|recruiting)@[^\s@<>]+\.[^\s@<>]+", address): continue
                domain = address.split("@")[1]
                if host != domain and not host.endswith("." + domain): continue
                positions = [m.start() for m in re.finditer(re.escape(address), plain, re.I)]
                for position in positions:
                    context = plain[max(0, position - 180):position + 100]
                    if re.search(r"(?:send|submit|senden|schicken).{0,110}(?:application|Bewerbung|Lebenslauf|CV)|(?:application|Bewerbung).{0,110}(?:email|e-mail|per Mail|senden|schicken)", context, re.I): found.add(address)
        if len(found) == 1: return found.pop()
        raise Pending("portal_required")
    if set(route) != {"url", "recipient", "proof"}: raise ValueError("invalid_route")
    target = route["recipient"]
    if not re.fullmatch(r"[^\s@<>?]+@[^\s@<>?]+\.[^\s@<>?]+", target): raise ValueError("invalid_recipient")
    if not route["url"].startswith("https://"): raise ValueError("invalid_route")
    # Cross-host email delivery is allowed only for an explicit owner-reviewed route.
    proof = fetch(route["url"])
    if proof.get("error") or proof.get("http") != 200 or proof["final_url"] != route["url"]: raise Pending("route_unverified")
    links = Links(); links.feed(proof["body"])
    if not any(unquote(href).casefold() == "mailto:" + target.casefold() for href, _ in links.links): raise Pending("route_unverified")
    plain = html.unescape(re.sub(r"<[^>]+>", " ", proof["body"]))
    if not route["proof"].strip() or route["proof"].casefold() not in re.sub(r"\s+", " ", plain).casefold(): raise Pending("route_unverified")
    return target


def compose(job, person, recipient, language, description, message_id):
    en = language == "en"
    document_paths = person["documents"][language]
    samples = bool(re.search(r"portfolio|work samples|Arbeitsproben", description, re.I))
    kinds = ["cv", "portfolio"] if samples else ["cv"]
    # Email accepts separate files. Portal adapters must use 'combined' for one slot.
    message = EmailMessage(policy=SMTP)
    message["From"] = formataddr((person["name"], person["email"]))
    message["To"] = recipient
    message["Subject"] = ("Application: " if en else "Bewerbung: ") + job["title"]
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = message_id
    focus = person.get("introduction", {}).get(language, "")
    if en:
        body = f"Dear recruiting team,\n\nI am applying for the position of {job['title']} at {job['company']}.\n\n{focus}\n\nPlease find my CV" + (" and portfolio" if samples else "") + " attached."
        body += f"\n\nI am available from {date.fromisoformat(person['available_from']).strftime('%d %B %Y')}."
        if re.search(r"salary|compensation expectation", description, re.I): body += f" My desired gross annual salary is EUR {person['salary_eur_year']:,}."
        body += "\n\nI would welcome the opportunity to discuss the role with you.\n\nBest regards,\n"
    else:
        body = f"Guten Tag,\n\nhiermit bewerbe ich mich als {job['title']} bei {job['company']}.\n\n{focus}\n\nMeinen Lebenslauf" + (" und mein Portfolio" if samples else "") + " finden Sie im Anhang."
        body += f"\n\nIch bin ab dem {date.fromisoformat(person['available_from']).strftime('%d.%m.%Y')} verfügbar."
        if re.search(r"Gehaltsvorstellung|Gehaltswunsch|Gehaltsangabe", description, re.I): body += f" Meine Gehaltsvorstellung liegt bei {person['salary_eur_year']:,} Euro brutto pro Jahr.".replace(",", ".")
        body += "\n\nIch freue mich darauf, mehr über die Aufgabe und Ihr Team zu erfahren.\n\nFreundliche Grüße\n"
    body += f"{person['name']}\n{person['address']}\n{person['phone']}\n{person['email']}\n\n" + job["original_url"]
    message.set_content(body)
    for kind in kinds:
        path = Path(document_paths[kind])
        message.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)
    return message


def record_sent(job, message_id, stamp):
    app_id = hashlib.sha256(("auto:" + job["id"]).encode()).hexdigest()[:24]
    with closing(applications.connect()) as db, db:
        db.execute("INSERT OR IGNORE INTO applications(id,company,title,job_id,confirmed,match_state,manual_link,created_at,applied_at) VALUES(?,?,?,?,1,'matched',1,?,?)", (app_id, job["company"], job["title"], job["id"], stamp, stamp))
        db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", ("auto:" + job["id"], app_id, message_id, stamp, "submitted", "high", "Bewerbung per E-Mail versendet", "", "SMTP-Server hat die Nachricht angenommen. Eine Eingangsbestätigung steht noch aus.", "automatic"))
    return app_id


def send(message, person, before_data):
    smtp = person["smtp"]
    secret = Path(smtp["credential_file"]).expanduser().read_text().strip()
    with smtplib.SMTP(smtp["host"], smtp["port"], timeout=40) as client:
        client.ehlo(); client.starttls(context=ssl.create_default_context()); client.ehlo()
        client.login(smtp["username"], secret)
        code, _ = client.mail(person["email"])
        if code != 250: raise Pending("sender_rejected")
        code, _ = client.rcpt(str(message["To"]))
        if code not in {250, 251}: raise Pending("recipient_rejected")
        # Durable uncertainty marker BEFORE DATA. Never retry after a timeout/crash.
        before_data()
        code, _ = client.data(message.as_bytes())
        if code != 250: raise Pending("delivery_unknown")


def run(dry_run=False):
    if not CONFIG["auto_apply"]["enabled"]: return {"status": "disabled"}
    person = profile()
    lock_path = ensure_data_dir() / "auto-apply.lock"
    with lock_path.open("a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {"status": "busy"}
        with closing(jobs_connect()) as jobs:
            candidates = [dict(r) for r in jobs.execute("SELECT * FROM jobs WHERE score>8 AND user_status NOT IN ('deleted','hidden','applied') ORDER BY score DESC,id")]
        counts = {"sent": 0, "pending": 0, "skipped": 0, "ready": 0}
        with closing(connect()) as db:
            for job in candidates:
                row = db.execute("SELECT * FROM application_outbox WHERE job_id=?", (job["id"],)).fetchone()
                # Reconcile local bookkeeping after a confirmed SMTP success, without resending.
                if row and row["state"] == "sent":
                    record_sent(job, row["message_id"], row["sent_at"]); counts["skipped"] += 1; continue
                if row and row["state"] in {"sending", "unknown", "failed"}:
                    counts["skipped"] += 1; continue
                if already_applied(job): counts["skipped"] += 1; continue
                stamp = now_iso()
                fingerprint = hashlib.sha256(job["canonical_key"].encode()).hexdigest()
                message_id = f"<jobfind-{fingerprint[:32]}@{person['email'].split('@')[1]}>"
                def update(state, reason="", recipient="", language="", sent_at=""):
                    db.execute("INSERT INTO application_outbox(job_id,fingerprint,company,title,state,reason,recipient,language,message_id,created_at,checked_at,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET state=excluded.state,reason=excluded.reason,recipient=excluded.recipient,language=excluded.language,checked_at=excluded.checked_at,sent_at=excluded.sent_at", (job["id"], fingerprint, job["company"], job["title"], state, reason, recipient, language, message_id, stamp, stamp, sent_at)); db.commit()
                try:
                    response, description, language = listing(job)
                    recipient = email_route(job, response)
                    message = compose(job, person, recipient, language, description, message_id)
                    counts["ready"] += 1
                    if dry_run: continue
                    # Re-check decisions immediately before transmitting personal data.
                    with closing(jobs_connect()) as jobs:
                        current = jobs.execute("SELECT score,user_status FROM jobs WHERE id=?", (job["id"],)).fetchone()
                    if not current or current["score"] <= 8 or current["user_status"] in {"deleted", "hidden", "applied"} or already_applied(job):
                        counts["skipped"] += 1; continue
                    update("preparing", recipient=recipient, language=language)
                    send(message, person, lambda: update("unknown", "delivery_unknown", recipient, language))
                    sent_at = now_iso()
                    update("sent", recipient=recipient, language=language, sent_at=sent_at)
                    record_sent(job, message_id, sent_at)
                    counts["sent"] += 1
                except Pending as error:
                    reason = str(error)
                    existing = db.execute("SELECT state FROM application_outbox WHERE job_id=?", (job["id"],)).fetchone()
                    if not dry_run and (not existing or existing["state"] != "unknown"): update("pending", reason)
                    counts["pending"] += 1
                except (OSError, ValueError, KeyError, smtplib.SMTPException):
                    # Never include credentials, message bodies or arbitrary server replies in logs.
                    existing = db.execute("SELECT state FROM application_outbox WHERE job_id=?", (job["id"],)).fetchone()
                    if not dry_run and (not existing or existing["state"] != "unknown"): update("pending", "mail_connection_failed")
                    counts["pending"] += 1
        return {"status": "dry_run" if dry_run else "ok", **counts}
