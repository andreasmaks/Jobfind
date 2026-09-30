#!/usr/bin/env python3
"""Small authenticated HTTP server for the private Hermes job portal."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = ROOT / "scripts" / "modules"
sys.path.insert(0, str(MODULES_DIR))

from store import DATA_DIR, company_logo_path, delete_job, list_jobs, metadata, restore_job, set_job_like, set_user_status
from config import CONFIG, ensure_data_dir
from local_settings import PRESENTATION, local_asset
SESSION_COOKIE = CONFIG.get("local", {}).get("session_cookie", "jf_session")
AUTH_FILE = DATA_DIR / "auth.json"
AUTH_DB = DATA_DIR / "auth.sqlite3"
HOST = "127.0.0.1"
PORT = CONFIG["server"]["port"]
PUBLIC_ORIGIN = CONFIG["server"]["public_origin"]
ALLOWED_ORIGINS = {PUBLIC_ORIGIN} if PUBLIC_ORIGIN else {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
ALLOWED_HOSTS = {urlsplit(origin).netloc for origin in ALLOWED_ORIGINS}
COOKIE_SECURITY = "; Secure" if PUBLIC_ORIGIN else ""
SESSION_LIFETIME = 30 * 24 * 60 * 60
FAILED_WINDOW = 15 * 60
failed_logins: dict[str, list[float]] = {}
failed_lock = threading.Lock()
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("assets/styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("assets/app.js", "text/javascript; charset=utf-8"),
    "/assets/api.js": ("assets/api.js", "text/javascript; charset=utf-8"),
    "/assets/offline.js": ("assets/offline.js", "text/javascript; charset=utf-8"),
    "/assets/ui.js": ("assets/ui.js", "text/javascript; charset=utf-8"),
    "/assets/i18n.js": ("assets/i18n.js", "text/javascript; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/assets/theme.js": ("assets/theme.js", "text/javascript; charset=utf-8"),
    "/assets/login.js": ("assets/login.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/assets/brand-mark.svg": ("assets/brand-mark.svg", "image/svg+xml"),
    "/login": ("login.html", "text/html; charset=utf-8"),
}
PUBLIC_ASSETS = {
    "/assets/i18n.js",
    "/sw.js",
    "/manifest.webmanifest",
    "/login",
    "/assets/login.js",
    "/assets/theme.js",
    "/assets/styles.css",
    "/favicon.svg",
    "/assets/brand-mark.svg",
}


def cookie_value(header: str, name: str) -> str:
    for item in header.split(";"):
        key, sep, value = item.strip().partition("=")
        if sep and key == name:
            return value.strip()
    return ""


def init_auth_db() -> None:
    ensure_data_dir()
    db = sqlite3.connect(AUTH_DB)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)")
        db.commit()
    finally:
        db.close()
    AUTH_DB.chmod(0o600)


def valid_session(token: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return False
    try:
        db = sqlite3.connect(f"file:{quote(str(AUTH_DB))}?mode=ro", uri=True, timeout=3)
        try:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            row = db.execute("SELECT expires_at FROM sessions WHERE token_hash=?", (digest,)).fetchone()
            return bool(row and float(row[0]) > time.time())
        finally:
            db.close()
    except (OSError, sqlite3.Error, ValueError):
        return False


def verify_password(password: str) -> bool:
    try:
        config = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        salt = bytes.fromhex(config["salt"])
        expected = bytes.fromhex(config["hash"])
        iterations = int(config["iterations"])
        if len(salt) != 32 or len(expected) != 32 or not 100_000 <= iterations <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    db = sqlite3.connect(AUTH_DB, timeout=3)
    try:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        db.execute("INSERT INTO sessions (token_hash, expires_at) VALUES (?, ?)", (digest, time.time() + SESSION_LIFETIME))
        db.commit()
    finally:
        db.close()
    return token


def delete_session(token: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return
    db = sqlite3.connect(AUTH_DB, timeout=3)
    try:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode("ascii")).hexdigest(),))
        db.commit()
    finally:
        db.close()


def client_key(handler: BaseHTTPRequestHandler) -> str:
    return handler.client_address[0]


def is_rate_limited(key: str) -> bool:
    with failed_lock:
        recent = [stamp for stamp in failed_logins.get(key, []) if stamp > time.time() - FAILED_WINDOW]
        failed_logins[key] = recent
        return len(recent) >= 5


def record_failed_login(key: str) -> None:
    with failed_lock:
        failed_logins.setdefault(key, []).append(time.time())


def clear_failed_logins(key: str) -> None:
    with failed_lock:
        failed_logins.pop(key, None)


def csrf_secret() -> bytes:
    path = DATA_DIR / ".csrf_secret"
    ensure_data_dir()
    if not path.exists():
        try:
            with path.open("x", encoding="ascii") as handle:
                handle.write(secrets.token_hex(32))
            path.chmod(0o600)
        except FileExistsError:
            pass
    return path.read_bytes().strip()


def csrf_token(session: str) -> str:
    return hmac.new(csrf_secret(), session.encode("utf-8"), hashlib.sha256).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = "Jobfind/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def valid_host(self) -> bool:
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self.send_json(403, {"ok": False, "error": "invalid_host"})
            return False
        return True

    def log_message(self, format: str, *args: object) -> None:
        print("jobfind:", self.command, urlsplit(self.path).path, args[1] if len(args) > 1 else "", flush=True)

    def send_body(self, status: int, body: bytes, content_type: str, *, location: str = "", headers: tuple[tuple[str, str], ...] = (), cache_control: str = "private, no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if location:
            self.send_header("Location", location)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_body(status, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8")

    def session(self) -> str:
        token = cookie_value(self.headers.get("Cookie", ""), SESSION_COOKIE)
        return token if valid_session(token) else ""

    def do_GET(self) -> None:
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        if path == "/api/health":
            self.send_json(200, {"ok": True, "service": "jobfind"})
            return
        if path == "/assets/local.css" and not local_asset(path):
            self.send_body(200, b"", "text/css; charset=utf-8", cache_control="no-cache")
            return
        if path == "/assets/local-manifest.json":
            self.send_json(200, {"assets": list(PRESENTATION["assets"])})
            return
        asset = local_asset(path)
        if asset and (asset[2] or self.session()):
            self.send_body(200, asset[0].read_bytes(), asset[1], cache_control="private, no-cache")
            return
        if path in PUBLIC_ASSETS:
            filename, content_type = ASSETS[path]
            self.send_body(200, (ROOT / filename).read_bytes(), content_type, cache_control="no-cache")
            return
        session = self.session()
        if not session:
            if path.startswith("/api/"):
                self.send_json(401, {"ok": False, "error": "auth_required"})
            else:
                self.send_body(302, b"", "text/plain", location="/login?next=" + quote("/"))
            return
        try:
            if path == "/api/jobs":
                self.send_json(200, {"ok": True, "jobs": list_jobs()})
            elif path == "/api/meta":
                self.send_json(200, {"ok": True, **metadata()})
            elif path == "/api/csrf":
                self.send_json(200, {"ok": True, "token": csrf_token(session)})
            elif re.fullmatch(r"/assets/company-logos/[0-9a-f]{24}\.png", path):
                logo = company_logo_path(path.rsplit("/", 1)[-1])
                if not logo or not logo.is_file():
                    self.send_json(404, {"ok": False, "error": "not_found"})
                else:
                    self.send_body(
                        200,
                        logo.read_bytes(),
                        "image/png",
                        cache_control="private, max-age=86400",
                    )
            elif path in ASSETS:
                filename, content_type = ASSETS[path]
                self.send_body(200, (ROOT / filename).read_bytes(), content_type)
            else:
                self.send_json(404, {"ok": False, "error": "not_found"})
        except (OSError, sqlite3.Error):
            self.send_json(503, {"ok": False, "error": "temporarily_unavailable"})

    def do_POST(self) -> None:
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        if path == "/login":
            self.handle_login()
            return
        if path == "/logout":
            self.handle_logout()
            return
        match = re.fullmatch(r"/api/jobs/([0-9a-f]{20})/(status|delete|restore|like|unlike)", path)
        if not match:
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        session = self.session()
        if not session:
            self.send_json(401, {"ok": False, "error": "auth_required"})
            return
        if self.headers.get("Origin", "").rstrip("/") not in ALLOWED_ORIGINS:
            self.send_json(403, {"ok": False, "error": "invalid_origin"})
            return
        if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf_token(session)):
            self.send_json(403, {"ok": False, "error": "invalid_csrf"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                self.send_json(413, {"ok": False, "error": "invalid_size"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("invalid_payload")
            action = match[2]
            if action == "delete":
                found = delete_job(match[1], payload.get("reasons"), payload.get("note", ""))
            elif action == "restore":
                found = restore_job(match[1])
            elif action in {"like", "unlike"}:
                found = set_job_like(match[1], action == "like")
            else:
                found = set_user_status(match[1], payload.get("status"))
            self.send_json(200 if found else 404, {"ok": found})
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "invalid_request"})
        except (OSError, sqlite3.Error):
            self.send_json(503, {"ok": False, "error": "temporarily_unavailable"})

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin", "").rstrip("/")
        return origin in ALLOWED_ORIGINS

    def handle_login(self) -> None:
        if not self.same_origin():
            self.send_json(403, {"ok": False, "error": "invalid_origin"})
            return
        key = client_key(self)
        if is_rate_limited(key):
            self.send_body(303, b"", "text/plain", location="/login?error=rate")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096 or self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
                raise ValueError("invalid form")
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            password = fields.get("password", [""])[0]
            if not isinstance(password, str) or len(password) > 256:
                raise ValueError("invalid password")
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"ok": False, "error": "invalid_request"})
            return
        if not verify_password(password):
            record_failed_login(key)
            self.send_body(303, b"", "text/plain", location="/login?error=pw")
            return
        clear_failed_logins(key)
        try:
            token = create_session()
        except (OSError, sqlite3.Error):
            self.send_json(503, {"ok": False, "error": "temporarily_unavailable"})
            return
        self.send_body(303, b"", "text/plain", location="/", headers=(
            ("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_LIFETIME}; HttpOnly{COOKIE_SECURITY}; SameSite=Strict"),
        ))

    def handle_logout(self) -> None:
        if not self.same_origin():
            self.send_json(403, {"ok": False, "error": "invalid_origin"})
            return
        session = self.session()
        if not session or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf_token(session)):
            self.send_json(403, {"ok": False, "error": "invalid_csrf"})
            return
        try:
            delete_session(session)
        except (OSError, sqlite3.Error):
            self.send_json(503, {"ok": False, "error": "temporarily_unavailable"})
            return
        self.send_body(303, b"", "text/plain", location="/login", headers=(
            ("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly{COOKIE_SECURITY}; SameSite=Strict"),
        ))


if __name__ == "__main__":
    if not AUTH_FILE.is_file():
        raise SystemExit("Zuerst ein eigenes Passwort mit jobfind.py password setzen.")
    init_auth_db()
    print(f"Jobfind: http://{HOST}:{PORT} (nur lokal)", flush=True)
    with ThreadingHTTPServer((HOST, PORT), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Jobfind beendet.")
