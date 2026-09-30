#!/usr/bin/env python3
"""Set the Jobfund password without storing plaintext in the project."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"
sys.path.insert(0, str(MODULES_DIR))

from store import DATA_DIR
from config import ensure_data_dir

AUTH_FILE = DATA_DIR / "auth.json"
AUTH_DB = DATA_DIR / "auth.sqlite3"
ITERATIONS = 600_000


def main() -> None:
    if sys.stdin.isatty():
        password = getpass.getpass("Eigenes Jobfind-Passwort: ")
        if password != getpass.getpass("Passwort wiederholen: "):
            raise SystemExit("Passwörter stimmen nicht überein.")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    if not 12 <= len(password) <= 256:
        raise SystemExit("Das Passwort muss 12 bis 256 Zeichen haben.")
    ensure_data_dir()
    salt = secrets.token_bytes(32)
    verifier = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    payload = {"algorithm": "pbkdf2_sha256", "iterations": ITERATIONS, "salt": salt.hex(), "hash": verifier.hex()}
    temporary = AUTH_FILE.with_name(f".{AUTH_FILE.name}.{secrets.token_hex(8)}.tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")))
    temporary.chmod(0o600)
    os.replace(temporary, AUTH_FILE)
    if AUTH_DB.exists():
        db = sqlite3.connect(AUTH_DB)
        try:
            db.execute("DELETE FROM sessions")
            db.commit()
        finally:
            db.close()
    print("Jobfind-Passwort gesetzt; bisherige Sitzungen wurden beendet.")


if __name__ == "__main__":
    main()
