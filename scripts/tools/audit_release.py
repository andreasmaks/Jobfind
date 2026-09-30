#!/usr/bin/env python3
"""Fail closed on unintended publication files; print locations, never secret values."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = set("""
.gitignore LICENSE LICENSE-lucide.txt README.md THIRD_PARTY.md jobfind.py
index.html login.html favicon.svg manifest.webmanifest sw.js requirements.txt
assets/api.js assets/app.js assets/brand-mark.svg assets/login.js assets/offline.js
assets/styles.css assets/theme.js assets/ui.js config/example.json
examples/demo.json examples/empty.json examples/error.json
hermes/context.py hermes/import_jobs.py hermes/prompt.txt
scripts/modules/config.py scripts/modules/store.py scripts/server/server.py
scripts/tools/set_password.py scripts/tools/audit_release.py scripts/start_server.sh
tests/check_release.py tests/check_setup.py tests/check_offline.mjs
docs/HERMES.md docs/IMPORT_FORMAT.md docs/RELEASE_CHECKLIST.md
""".split())
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


def main() -> int:
    findings = []
    observed = set()
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in {".git", ".runtime", ".venv", "__pycache__"} for part in rel.parts):
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
        try:
            data.decode("utf-8")
        except UnicodeError:
            findings.append(f"{name}: unreviewed binary content")
        scan(data, name, findings)
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
            if kind in {b"blob", b"commit", b"tag"}:
                scan(run_git("cat-file", "-p", oid).stdout, "history/" + label, findings)
    for finding in sorted(set(findings)):
        print("REVIEW:", finding)
    print(f"publication_files={len(observed)} history_commits={commits} findings={len(set(findings))}")
    print("Pattern/allowlist audit only. Owner review and browser/live-search checks remain separate.")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
