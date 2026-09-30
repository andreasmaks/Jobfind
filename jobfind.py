#!/usr/bin/env python3
"""Small local entry point; only the standard library, no implicit Hermes calls."""
from __future__ import annotations

import argparse
import json
import os
import runpy
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        handle.write(content)


def initialize(path: Path, demo: bool = False) -> None:
    if path.exists():
        raise ValueError("Konfiguration existiert bereits; sie wird nicht überschrieben.")
    cfg = json.loads((ROOT / "config/example.json").read_text())
    if demo:
        cfg["data_dir"] = str(ROOT / ".runtime/demo")
        cfg["hermes"]["output_dir"] = str(ROOT / ".runtime/demo-output")
        cfg["server"]["port"] = 8124
        cfg["max_new_jobs_per_day"] = 8
    write_private(path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    print("Eigene Konfiguration angelegt:", path)


def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 oder neuer ist erforderlich.")
    parser = argparse.ArgumentParser(description="Jobfind mit Hermes-Integration")
    parser.add_argument("--config", type=Path, help="Eigene JSON-Konfiguration (vor dem Unterbefehl)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Neutrale eigene Konfiguration erstellen")
    commands.add_parser("doctor", help="Voraussetzungen, Konfiguration und freien Port prüfen")
    commands.add_parser("password", help="Eigenes Passwort setzen; aktive Sitzungen beenden")
    commands.add_parser("start", help="App im Vordergrund starten; Stopp mit Ctrl+C")
    demo = commands.add_parser("demo", help="Getrennte erfundene Demo initialisieren und starten")
    demo.add_argument("--prepare-only", action="store_true", help="Vorbereiten ohne Serverstart")
    importer = commands.add_parser("import", help="Eine Ergebnisdatei importieren oder konfigurierten Ordner lesen")
    importer.add_argument("file", type=Path, nargs="?")
    commands.add_parser("context", help="Aktuelles Profil und Feedback ausgeben (enthält private Daten)")
    commands.add_parser("hermes-prepare", help="Pre-Run-Shim und Prompt lokal erzeugen; nichts installieren")
    args = parser.parse_args()
    os.umask(0o077)
    config_path = (args.config or Path(os.environ.get("JOBFIND_CONFIG", ROOT / "config/jobfind.json"))).expanduser().resolve()
    if args.command == "demo":
        if args.config:
            raise ValueError("Demo verwendet ausschließlich config/demo.json.")
        config_path = ROOT / "config/demo.json"
        if not config_path.exists():
            initialize(config_path, demo=True)
    if args.command == "init":
        initialize(config_path)
        return 0
    os.environ["JOBFIND_CONFIG"] = str(config_path)
    sys.path.insert(0, str(ROOT / "scripts/modules"))
    sys.path.insert(0, str(ROOT / "hermes"))
    from config import CONFIG, ensure_data_dir
    if args.command == "doctor":
        print("Python:", sys.version.split()[0], "| SQLite:", __import__("sqlite3").sqlite_version)
        print("Konfiguration gültig | Zeitzone:", CONFIG["timezone"])
        print("Daten:", CONFIG["data_path"])
        print("Passwort:", "gesetzt" if (CONFIG["data_path"] / "auth.json").exists() else "noch setzen")
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", CONFIG["server"]["port"]))
            except OSError:
                print("Port belegt; laufende Instanz oder anderen Port prüfen.")
                return 1
        print("Lokaler Port frei:", CONFIG["server"]["port"])
        return 0
    if args.command == "password":
        runpy.run_path(str(ROOT / "scripts/tools/set_password.py"), run_name="__main__")
        return 0
    if args.command == "context":
        from context import build_context
        print(build_context())
        return 0
    if args.command == "hermes-prepare":
        setup = ensure_data_dir() / "hermes-setup"
        shim = setup / "jobfind-context.py"
        shim_text = ("# Jobfind pre-run shim. Generated locally; no credentials.\n"
                     "import os, subprocess\n"
                     f"env = dict(os.environ, JOBFIND_CONFIG={str(config_path)!r})\n"
                     f"subprocess.run([{sys.executable!r}, {str(ROOT / 'jobfind.py')!r}, 'context'], "
                     "env=env, check=True)\n")
        importer_shim = setup / "jobfind-import.py"
        import_text = ("# Jobfind importer shim. Generated locally; no model calls.\n"
                       "import os, subprocess\n"
                       f"env = dict(os.environ, JOBFIND_CONFIG={str(config_path)!r})\n"
                       f"subprocess.run([{sys.executable!r}, {str(ROOT / 'jobfind.py')!r}, 'import'], "
                       "env=env, check=True)\n")
        prompt = setup / "prompt.txt"
        for path, content in [(shim, shim_text), (importer_shim, import_text), (prompt, (ROOT / "hermes/prompt.txt").read_text())]:
            if path.exists():
                if path.read_text() != content:
                    raise ValueError("Hermes-Vorbereitung existiert mit anderem Inhalt; vor Erneuerung prüfen.")
            else:
                write_private(path, content)
        print("Pre-Run-Shim:", shim)
        print("Importer-Shim:", importer_shim)
        print("Prompt:", prompt)
        print("Es wurde nichts in Hermes installiert oder aktiviert. Weiter in docs/HERMES.md.")
        return 0
    if args.command == "import":
        from import_jobs import import_file, scan_output
        result = import_file(args.file.expanduser().resolve()) if args.file else scan_output()
        print(json.dumps(result, ensure_ascii=False))
        return int(bool(result.get("errors") or result.get("run_status") == "error"))
    if args.command == "demo":
        if CONFIG["data_path"] != (ROOT / ".runtime/demo").resolve() or CONFIG["server"]["public_origin"]:
            raise ValueError("Demo muss ihr eigenes lokales Datenverzeichnis verwenden.")
        if not (ensure_data_dir() / "auth.json").exists():
            print("Auch die Demo benötigt dein eigenes Passwort (mindestens 12 Zeichen).")
            runpy.run_path(str(ROOT / "scripts/tools/set_password.py"), run_name="__main__")
        from import_jobs import import_file
        print("Erfundene Demo:", json.dumps(import_file(ROOT / "examples/demo.json")))
        if args.prepare_only:
            return 0
    if args.command in {"start", "demo"}:
        os.execv(sys.executable, [sys.executable, str(ROOT / "scripts/server/server.py")])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, TypeError, KeyError) as error:
        print("Jobfind:", str(error), file=sys.stderr)
        raise SystemExit(1)
