"""Read-only IMAP application evidence. No mail mutations and no external AI."""
from __future__ import annotations

import email
import fcntl
import hashlib
import imaplib
import json
import re
import ssl
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.policy import default
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from config import CONFIG, ensure_data_dir
from store import connect as jobs_connect, now_iso
from applications import connect, ingest_message

SEARCH_TERMS = ("Bewerb", "application", "interview", "Absage", "Kennenlernen", "Vorstellung", "Recruit", "ckmeldung", "Gespr", "Arbeitsvertrag", "candidacy")
MAX_MESSAGE = 262144


class MailError(Exception):
    pass


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}: self.ignored += 1
        if tag in {"p", "div", "br", "li", "tr"}: self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.ignored: self.ignored -= 1
        if tag in {"p", "div", "li", "tr"}: self.parts.append("\n")
    def handle_data(self, data):
        if not self.ignored: self.parts.append(data)


def header(value):
    try: return str(make_header(decode_header(str(value or ""))))
    except (ValueError, LookupError, UnicodeError): return str(value or "")


def current_text(text):
    lines = text.replace("\r", "").splitlines()
    kept = []
    for line in lines:
        if re.match(r"\s*(?:Am .{5,120} schrieb|On .{5,120} wrote:|_{5,}|-{3,}\s*(?:Original|Forwarded)|Von:|From:)", line, re.I): break
        if line.lstrip().startswith(">"): continue
        kept.append(line)
    return re.sub(r"[ \t]+", " ", "\n".join(kept)).strip()[:14000]


def decode_message(raw, fallback_id, sent=False):
    message = email.message_from_bytes(raw, policy=default)
    texts, html = [], []
    for part in message.walk():
        if part.get_content_disposition() == "attachment" or part.get_content_maintype() == "multipart": continue
        if part.get_content_type() not in {"text/plain", "text/html"}: continue
        try: content = part.get_content()
        except (LookupError, UnicodeError, ValueError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if not isinstance(content, str): continue
        if part.get_content_type() == "text/plain": texts.append(content)
        else: html.append(content)
    body = "\n".join(texts)
    if not body:
        parser = Text()
        parser.feed("\n".join(html))
        body = "".join(parser.parts)
    try: date = parsedate_to_datetime(str(message.get("Date", "")))
    except (ValueError, TypeError, OverflowError): date = None
    # An undated mail remains evidence but is explicitly placed at sync time.
    if date is None: date = datetime.now(timezone.utc)
    if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
    message_id = str(message.get("Message-ID", "")).strip() or fallback_id
    references = re.findall(r"<[^<>\r\n]{3,500}>", str(message.get("In-Reply-To", "")) + " " + str(message.get("References", "")))
    return {"key": hashlib.sha256(message_id.encode()).hexdigest(), "message_id": message_id[:600],
        "references": list(reversed(references[-30:])), "subject": header(message.get("Subject"))[:500],
        "sender": header(message.get("From"))[:400], "recipient": header(message.get("To"))[:400], "received_at": date.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "body": current_text(body), "sent": sent}


def classify_message(message):
    subject, body = message["subject"], message["body"]
    text = re.sub(r"\s+", " ", subject + " " + body).casefold()
    if re.search(r"job.?alert|jobs (?:for you|für dich)|stellenempfehlung|bewerbungstipps|newsletter|regarding.*visa|tourist visa|beta[ -]?test|testflight|beta program|wohnungsbewerbung|mietbewerbung|wohnungsbesichtigung|rental application|mortgage application|loan application", text[:1500]): return None
    context = bool(re.search(r"bewerb|(?:your|my|the) application|application (?:for|received|status)|applied for|candidacy|job offer|vorstellungsgespr|(?:interview|gespräch).{0,90}(?:position|stelle|recruit)|(?:position|stelle|recruit).{0,90}interview", text))
    if not context: return None
    def result(status, proof=True): return {"status": status, "confidence": "high" if proof else "review", "proof": proof}
    if re.search(r"(?:ziehe|ziehen).{0,90}bewerbung.{0,60}zurück|withdraw (?:my|your) application|rückzug.{0,70}bewerbung", text):
        return result("withdrawn")
    if message["sent"]:
        if re.search(r"hiermit bewerbe|anbei.{0,40}meine bewerbung|i am applying|my application for|attached.{0,30}(?:my cv|my resume)", text):
            return result("submitted")
        return result("message", False)
    if re.search(r"(?:prozess|auswahlverfahren).{0,80}mit anderen (?:bewerbenden|kandidat\w*|bewerber\w*).{0,60}(?:fort(?:zu)?setz|weiter)|(?:haben|hat).{0,70}für (?:eine[nm]? )?ander\w* (?:kandidat\w*|bewerber\w*).{0,50}entschieden|position.{0,60}anderweitig besetzt", text):
        return result("rejected")
    if re.search(r"nicht.{0,60}berücksichtig|not (?:be )?moving forward|not.{0,35}proceeding|decided.{0,70}(?:other|another) candidat|leider.{0,150}(?:absagen|ander\w* bewerber|ander\w* kandidat|nicht weiter)|unfortunately.{0,150}(?:unsuccessful|not|filled)|bewerbung.{0,70}absage", text) or (re.search(r"\babsage\b", subject, re.I) and re.search(r"bewerbung|application", text)):
        return result("rejected")
    if re.search(r"arbeitsvertrag|offer of employment|job offer|möchten.{0,70}(?:stelle|position).{0,40}anbieten|employment offer", text):
        return result("offer")
    if re.search(r"einladung.{0,90}(?:interview|gespräch|gespraech)|laden.{0,60}(?:dich|sie).{0,100}(?:gespräch|interview)|invite you.{0,80}interview|interview invitation|schedule.{0,70}interview", text):
        return result("interview", bool(re.search(r"bewerb|application|candidacy", text)))
    if re.search(r"bewerbung.{0,80}(?:in prüfung|wird.{0,30}geprüft)|reviewing your application|application.{0,80}under review", text):
        return result("reviewing")
    if re.search(r"dank.{0,45}(?:deine|ihre|die) bewerbung|bewerbung.{0,65}(?:eingegangen|erhalten)|(?:thank you|thanks) for (?:your application|applying)|received your application|application.{0,60}(?:received|successfully submitted)", text):
        return result("submitted")
    return result("message", False)


def ids(response):
    status, data = response
    if status != "OK": raise MailError("mail_search_failed")
    return [int(value) for value in (data[0] or b"").split()] if data else []


def search_expression():
    parts = ['SUBJECT "' + term + '"' for term in SEARCH_TERMS]
    expression = parts[-1]
    for part in reversed(parts[:-1]): expression = "OR " + part + " " + expression
    return "(" + expression + ")"


def sync_applications(client_factory=None):
    settings = CONFIG["applications_mail"]
    if not settings["enabled"]: return {"status": "disabled"}
    lock_path = ensure_data_dir() / "applications-sync.lock"
    with lock_path.open("a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {"status": "already_running"}
        with closing(connect()) as db, db:
            db.execute("UPDATE sync_state SET status='running',checked_at=?,error='' WHERE id=1", (now_iso(),))
        mail, inserted, scanned, more = None, 0, 0, False
        try:
            credential = Path(settings["credential_file"]).expanduser()
            if credential.stat().st_mode & 0o077: raise MailError("mail_credential_permissions")
            secret = credential.read_text().strip()
            mail = client_factory() if client_factory else imaplib.IMAP4_SSL(settings["host"], settings["port"],
                ssl_context=ssl.create_default_context(), timeout=20)
            try: mail.login(settings["username"], secret)
            except imaplib.IMAP4.error: raise MailError("mail_login_failed") from None
            with closing(jobs_connect()) as db:
                jobs = [dict(row) for row in db.execute("SELECT id,title,company,original_url,user_status,first_seen_at FROM jobs")]
            for folder in settings["folders"]:
                name = folder["name"]
                quoted = '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'
                status, _ = mail.select(quoted, readonly=True)
                if status != "OK": raise MailError("mail_folder_unavailable")
                _, validity_data = mail.response("UIDVALIDITY")
                validity = (validity_data[0] or b"").decode() if validity_data else ""
                if not validity: raise MailError("mail_uidvalidity_missing")
                key = hashlib.sha256((settings["host"] + "|" + settings["username"] + "|" + name).encode()).hexdigest()
                with closing(connect()) as db:
                    row = db.execute("SELECT * FROM mailbox_state WHERE folder_key=?", (key,)).fetchone()
                    state = dict(row) if row and row["uidvalidity"] == validity else None
                limit = settings["max_messages_per_folder"]
                all_uids = ids(mail.uid("search", None, "ALL"))
                highest = max(all_uids, default=0)
                if state is None:
                    matching = ids(mail.uid("search", None, search_expression()))
                    pending = sorted(matching, reverse=True)[:limit]
                    backfill = min(pending) if len(matching) > len(pending) else 0
                    high = highest
                else:
                    new = sorted(uid for uid in all_uids if uid > state["high_uid"])
                    pending = new[:limit]
                    high = max(pending, default=state["high_uid"])
                    backfill = state["backfill_uid"]
                    if len(pending) < limit and backfill:
                        older = ids(mail.uid("search", None, "UID 1:" + str(backfill - 1) + " " + search_expression())) if backfill > 1 else []
                        batch = sorted(older, reverse=True)[:limit - len(pending)]
                        pending.extend(batch)
                        backfill = min(batch) if len(older) > len(batch) else 0
                # Fetch without \Seen; no STORE, COPY, MOVE, EXPUNGE or SMTP operations.
                decoded = []
                for uid in pending:
                    status, parts = mail.uid("fetch", str(uid), "(BODY.PEEK[]<0." + str(MAX_MESSAGE) + ">)")
                    if status != "OK": raise MailError("mail_fetch_failed")
                    raw = next((part[1] for part in parts if isinstance(part, tuple) and isinstance(part[1], bytes)), None)
                    if raw is None: continue  # Mail moved between SEARCH and FETCH.
                    message = decode_message(raw, key + ":" + validity + ":" + str(uid), folder["sent"])
                    decoded.append(message)
                    scanned += 1
                for message in sorted(decoded, key=lambda m: m["received_at"]):
                    inserted += int(ingest_message(message, classify_message(message), jobs))
                more = more or bool(backfill) or bool(high < highest)
                with closing(connect()) as db, db:
                    db.execute("INSERT OR REPLACE INTO mailbox_state VALUES(?,?,?,?)", (key, validity, high, backfill))
            with closing(connect()) as db, db:
                db.execute("UPDATE sync_state SET status='ok',checked_at=?,last_success_at=?,error='',more_history=? WHERE id=1", (now_iso(), now_iso(), int(more)))
            return {"status": "ok", "scanned": scanned, "new_events": inserted, "more_history": more}
        except (MailError, OSError, imaplib.IMAP4.error, ValueError, TypeError, sqlite3.Error, UnicodeError) as exc:
            code = str(exc) if isinstance(exc, MailError) else "mail_sync_failed"
            with closing(connect()) as db, db:
                db.execute("UPDATE sync_state SET status='error',checked_at=?,error=? WHERE id=1", (now_iso(), code))
            return {"status": "error", "error": code}
        finally:
            if mail:
                try: mail.logout()
                except (OSError, imaplib.IMAP4.error): pass


_worker_lock = threading.Lock()
_worker = None


def start_sync():
    """One background worker per server; the file lock also covers scheduled CLI runs."""
    global _worker
    with _worker_lock:
        if _worker and _worker.is_alive(): return False
        _worker = threading.Thread(target=sync_applications, name="applications-mail-sync", daemon=True)
        _worker.start()
        return True
