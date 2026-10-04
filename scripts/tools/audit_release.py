#!/usr/bin/env python3
"""Fail closed on unintended publication files; print locations, never secret values."""
from __future__ import annotations

import hashlib
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = set("""
.gitignore LICENSE LICENSE-lucide.txt README.md README.de.md THIRD_PARTY.md jobfind.py
Screen-1.png Screen-2.png
index.html login.html favicon.svg manifest.webmanifest sw.js requirements.txt
assets/api.js assets/app.js assets/brand-mark.svg assets/login.js assets/offline.js assets/i18n.js
assets/styles.css assets/theme.js assets/ui.js config/example.json
examples/demo.json examples/empty.json examples/error.json
hermes/context.py hermes/import_jobs.py hermes/prompt.txt
scripts/modules/config.py scripts/modules/store.py scripts/modules/local_settings.py scripts/modules/availability.py scripts/server/server.py
scripts/tools/set_password.py scripts/tools/audit_release.py scripts/start_server.sh
tests/check_release.py tests/check_setup.py tests/check_offline.mjs tests/check_local.py tests/check_i18n.mjs tests/check_availability.py
docs/HERMES.md docs/IMPORT_FORMAT.md docs/RELEASE_CHECKLIST.md docs/DEVELOPMENT.md
""".split())
REVIEWED_PNGS = {
    "Screen-1.png": "cb256e6fbd888622b750b23d1e38fd1fc1739795bc13b4f85c3d40eb9ba27176",
    "Screen-2.png": "66ebfc7f97b195367375076a02962ec8d30320eaa2c672917cc27ed3cb1b6d85",
}
PATTERNS = {
    "private absolute user path": re.compile(rb"/Users/[A-Za-z0-9_.-]+/"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider or GitHub credential": re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b"),
    "literal credential assignment": re.compile(rb"(?im)^\s*(?:password|api_key|access_token)\s*=\s*['\"][^'\"\r\n]{8,}['\"]"),
}


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)


def scan(data: bytes, location: str, findings: list[str]) -> None:
    for label, pattern in PATTERNS.items():
        if pattern.search(data):
            findings.append(f"{location}: {label}")


def review_content(data: bytes, name: str, location: str, findings: list[str]) -> None:
    if name in REVIEWED_PNGS:
        valid_header = (len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n"
                        and data[8:16] == b"\x00\x00\x00\rIHDR"
                        and struct.unpack(">II", data[16:24]) == (3708, 2560))
        if not valid_header or hashlib.sha256(data).hexdigest() != REVIEWED_PNGS[name]:
            findings.append(f"{location}: image differs from visually reviewed original")
        return
    try:
        data.decode("utf-8")
    except UnicodeError:
        findings.append(f"{location}: unreviewed binary content")
    scan(data, location, findings)


def main() -> int:
    findings = []
    observed = set()
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in {".git", ".runtime", ".venv", ".private", "logs", ".work", "__pycache__"} for part in rel.parts):
            continue
        if path.name == ".DS_Store" or (rel.parent == Path("config") and path.name != "example.json"):
            continue
        if path.is_symlink():
            findings.append(f"{rel}: symlink requires review")
            continue
        if not path.is_file():
            continue
        name = rel.as_posix()
        observed.add(name)
        if name not in PUBLIC_FILES:
            findings.append(f"{name}: unexpected publication file")
            continue
        data = path.read_bytes()
        review_content(data, name, name, findings)
    for name in sorted(PUBLIC_FILES - observed):
        findings.append(f"{name}: missing publication file")
    commits = 0
    if (ROOT / ".git").exists():
        tracked = {p.decode() for p in run_git("ls-files", "-z").stdout.split(b"\0") if p}
        for name in sorted(tracked - PUBLIC_FILES):
            findings.append(f"{name}: unintended tracked file")
        for name in sorted(PUBLIC_FILES - tracked):
            findings.append(f"{name}: publication file not staged/tracked")
        log = run_git("rev-list", "--all").stdout
        commits = len(log.splitlines())
        objects = run_git("rev-list", "--objects", "--all").stdout.splitlines()
        for entry in objects:
            oid = entry.split(b" ", 1)[0].decode()
            label = entry.split(b" ", 1)[1].decode(errors="replace") if b" " in entry else "Git metadata"
            kind = run_git("cat-file", "-t", oid).stdout.strip()
            if kind == b"blob" and label not in PUBLIC_FILES:
                findings.append(f"history/{label}: unintended historical file")
            if kind == b"blob":
                review_content(run_git("cat-file", "-p", oid).stdout, label, "history/" + label, findings)
            elif kind in {b"commit", b"tag"}:
                scan(run_git("cat-file", "-p", oid).stdout, "history/" + label, findings)
    for finding in sorted(set(findings)):
        print("REVIEW:", finding)
    print(f"publication_files={len(observed)} history_commits={commits} findings={len(set(findings))}")
    print("Pattern/allowlist audit only. Owner review and browser/live-search checks remain separate.")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
