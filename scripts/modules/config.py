"""One configuration for the app, importer and Hermes context. No legacy paths."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("JOBFIND_CONFIG", ROOT / "config/jobfind.json")).expanduser().resolve()


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Konfiguration fehlt oder ist ungültig; zuerst jobfind.py init ausführen.") from exc
    if not isinstance(cfg, dict) or cfg.get("config_version") != 1:
        raise ValueError("config_version muss 1 sein")
    required = {"config_version", "data_dir", "server", "search", "max_new_jobs_per_day", "timezone", "hermes"}
    if set(cfg) - (required | {"local"}) or not required <= set(cfg):
        raise ValueError("Unbekannte oder fehlende Konfigurationsfelder")
    ZoneInfo(cfg["timezone"])
    if type(cfg["max_new_jobs_per_day"]) is not int or not 1 <= cfg["max_new_jobs_per_day"] <= 100:
        raise ValueError("Tageslimit muss zwischen 1 und 100 liegen")
    server = cfg["server"]
    if set(server) != {"bind", "port", "public_origin"}:
        raise ValueError("Ungültige Serverkonfiguration")
    if server["bind"] not in {"127.0.0.1", "localhost"}:
        raise ValueError("Diese Version bindet ausschließlich an IPv4-Loopback")
    if type(server["port"]) is not int or not 1024 <= server["port"] <= 65535:
        raise ValueError("Ungültiger Port")
    from urllib.parse import urlsplit
    origin = server["public_origin"]
    if not isinstance(origin, str):
        raise ValueError("Ungültiger öffentlicher Ursprung")
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("public_origin muss ein reiner HTTPS-Ursprung sein")
    search = cfg["search"]
    if set(search) != {"region", "roles", "activities", "weekly_hours", "work_models", "hard_exclusions", "soft_preferences"}:
        raise ValueError("Ungültiges Suchprofil")
    region = search["region"]
    if set(region) != {"allowed_places", "excluded_places", "ambiguous_labels", "allow_remote_without_local_place"}:
        raise ValueError("Ungültige Regionsregeln")
    if type(region["allow_remote_without_local_place"]) is not bool:
        raise ValueError("Ungültige Remote-Regel")
    for values in [region["allowed_places"], region["excluded_places"], region["ambiguous_labels"],
                   search["roles"], search["activities"], search["work_models"],
                   search["hard_exclusions"], search["soft_preferences"]]:
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or not v.strip() or len(v) > 600 for v in values):
            raise ValueError("Profilfelder müssen Listen kurzer Texte sein")
    if not region["allowed_places"] or not search["roles"]:
        raise ValueError("Mindestens ein Ort und eine Rolle sind erforderlich")
    if not isinstance(search["weekly_hours"], str) or len(search["weekly_hours"]) > 600:
        raise ValueError("Ungültige Arbeitszeit")
    hermes = cfg["hermes"]
    if set(hermes) != {"job_id", "output_dir", "schedule"}:
        raise ValueError("Ungültige Hermes-Konfiguration")
    if not isinstance(hermes["job_id"], str) or (hermes["job_id"] and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", hermes["job_id"])):
        raise ValueError("Ungültige Hermes-Auftragskennung")
    if not isinstance(hermes["schedule"], str) or len(hermes["schedule"]) > 100:
        raise ValueError("Ungültiger Zeitplan")
    def resolve(value: str) -> Path:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("Ungültiger Laufzeitpfad")
        result = Path(value).expanduser()
        return (path.parent / result).resolve() if not result.is_absolute() else result.resolve()
    cfg["data_path"] = resolve(cfg["data_dir"])
    cfg["output_path"] = resolve(hermes["output_dir"])
    local = cfg.get("local", {})
    if not isinstance(local, dict) or set(local) - {"presentation_file", "assets_dir", "profile_file", "import_hook", "session_cookie", "legacy_run_ids"}:
        raise ValueError("Ungültige lokale Erweiterung")
    cookie = local.get("session_cookie", "jf_session")
    if not isinstance(cookie, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", cookie):
        raise ValueError("Ungültiger Sitzungsname")
    if type(local.get("legacy_run_ids", False)) is not bool:
        raise ValueError("Ungültige Altimport-Einstellung")
    cfg["local_paths"] = {key: resolve(local[key]) for key in {"presentation_file", "assets_dir", "profile_file", "import_hook"} & local.keys()}
    validate_data_dir(cfg["data_path"])
    return cfg


def validate_data_dir(data: Path) -> None:
    # Refuse an existing unrelated directory before chmod, mkdir or SQLite writes.
    if data.resolve() != data:
        raise ValueError("Laufzeitpfad wurde während des Betriebs umgeleitet")
    if data == ROOT or data == ROOT.parent or data in ROOT.parents:
        raise ValueError("Datenverzeichnis darf kein Code- oder übergeordnetes Verzeichnis sein")
    if data.exists():
        marker = data / ".jobfind-runtime"
        if any(data.iterdir()) and (not marker.is_file() or marker.read_text().strip() != "jobfind-runtime-v1"):
            raise ValueError("Bestehendes fremdes Datenverzeichnis: Zugriff verweigert")


CONFIG = load_config()


def ensure_data_dir() -> Path:
    data = CONFIG["data_path"]
    # Revalidate immediately before every database write, including after config load.
    validate_data_dir(data)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.chmod(0o700)
    marker = data / ".jobfind-runtime"
    if not marker.exists():
        marker.write_text("jobfind-runtime-v1\n", encoding="ascii")
        marker.chmod(0o600)
    return data


def is_allowed_location(job: dict) -> bool:
    """Literal, bounded place matching; no user-provided regular expressions."""
    region = CONFIG["search"]["region"]
    location = job.get("location", "").casefold()
    def contains(term: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", location))
    if any(contains(t) for t in region["excluded_places"] + region["ambiguous_labels"]):
        return False
    if any(contains(t) for t in region["allowed_places"]):
        return True
    return region["allow_remote_without_local_place"] and job.get("work_model") == "remote"
