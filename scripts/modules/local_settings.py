"""Optional local appearance; private files are never required by a public install."""
from __future__ import annotations

import json
import re
from pathlib import Path
from config import CONFIG, ROOT

MIME_TYPES = {".css": "text/css; charset=utf-8", ".ttf": "font/ttf", ".woff2": "font/woff2",
              ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".svg": "image/svg+xml", ".ico": "image/x-icon",
              ".webmanifest": "application/manifest+json; charset=utf-8"}
URL_PATTERN = re.compile(r"/(?:assets/(?:fonts|logos|local)/[A-Za-z0-9_.-]+|assets/local\.css|favicon\.svg|favicon\.ico|apple-touch-icon\.png|manifest\.webmanifest)")


def load_presentation() -> dict:
    path = CONFIG["local_paths"].get("presentation_file")
    if not path:
        return {"assets": {}, "company_logos": {}, "part_time_terms": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"assets", "company_logos", "part_time_terms"}:
        raise ValueError("Ungültige private Darstellung")
    if not isinstance(data["assets"], dict) or len(data["assets"]) > 200:
        raise ValueError("Ungültige lokale Assets")
    base = CONFIG["local_paths"].get("assets_dir", ROOT / ".private/assets").resolve()
    for url, record in data["assets"].items():
        if not isinstance(url, str) or not URL_PATTERN.fullmatch(url) or not isinstance(record, dict) or set(record) != {"file", "public"}:
            raise ValueError("Ungültige lokale Asset-Zuordnung")
        if not isinstance(record["file"], str) or type(record["public"]) is not bool:
            raise ValueError("Ungültige lokale Asset-Zuordnung")
        relative = Path(record["file"])
        target = (base / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(base) or target.suffix not in MIME_TYPES or not target.is_file():
            raise ValueError("Lokales Asset liegt außerhalb des Asset-Verzeichnisses oder fehlt")
        record["path"] = target
        record["content_type"] = MIME_TYPES[target.suffix]
    logos = data["company_logos"]
    if not isinstance(logos, dict) or len(logos) > 500:
        raise ValueError("Ungültige lokale Firmenlogos")
    for company, record in logos.items():
        if not isinstance(company, str) or len(company) > 300 or not isinstance(record, dict) or set(record) - {"url", "dark_url", "mode"}:
            raise ValueError("Ungültige Firmenlogo-Zuordnung")
        for field in ["url", "dark_url"]:
            if field in record and (not isinstance(record[field], str) or record[field] not in data["assets"]):
                raise ValueError("Firmenlogo muss ein freigegebenes lokales Asset sein")
        if "url" not in record or record.get("mode", "alpha") not in {"alpha", "dark", "light", "tone"}:
            raise ValueError("Ungültiger Firmenlogo-Modus")
    terms = data["part_time_terms"]
    if not isinstance(terms, list) or len(terms) > 30 or any(not isinstance(t, str) or not t or len(t) > 40 for t in terms):
        raise ValueError("Ungültige lokale Arbeitszeit-Markierungen")
    return data


PRESENTATION = load_presentation()


def local_asset(url: str) -> tuple[Path, str, bool] | None:
    record = PRESENTATION["assets"].get(url)
    if not record:
        return None
    # Re-resolve on every request, so a later symlink replacement cannot escape.
    base = CONFIG["local_paths"].get("assets_dir", ROOT / ".private/assets").resolve()
    path = (base / record["file"]).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("Lokales Asset wurde umgeleitet")
    return path, record["content_type"], record["public"]


def decorate_job(job: dict) -> None:
    logo = PRESENTATION["company_logos"].get(job["company"].strip().casefold())
    if logo:
        job["company_logo_url"] = logo["url"]
        job["company_logo_mode"] = logo.get("mode", "alpha")
        job["company_logo_dark_url"] = logo.get("dark_url", "")
    hours = re.sub(r"\s+", "", job.get("hours", "")).casefold()
    job["part_time_hint"] = any(re.search(r"(?<!\d)" + re.escape(re.sub(r"\s+", "", term).casefold()) + r"(?!\d)", hours)
                                for term in PRESENTATION["part_time_terms"])
