#!/usr/bin/env python3
"""Bounded schema-v1 importer. No network calls and no historical guessing."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/modules"))
from config import CONFIG, is_allowed_location
from store import canonical_url, has_run, import_run, normalize_job, now_iso

MAX_BYTES = 1024 * 1024
TEXT_FIELDS = {"title", "company", "original_url", "source", "source_id", "location", "remote", "hours",
               "employment_type", "posted_at", "checked_at", "found_at", "summary", "fit", "concerns",
               "availability", "work_model"}


def parse_json_response(response: str) -> dict:
    response = response.strip()
    if response.startswith("```json\n") and response.endswith("```"):
        response = response[8:-3].strip()
    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate_json_key")
            obj[key] = value
        return obj
    payload = json.loads(response, object_pairs_hook=unique_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json_constant")))
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("invalid_schema_version")
    if set(payload) - {"schema_version", "run_id", "ran_at", "run_status", "jobs", "company_profiles", "error"}:
        raise ValueError("unknown_envelope_field")
    status, jobs, profiles = payload.get("run_status"), payload.get("jobs"), payload.get("company_profiles", [])
    if not isinstance(status, str) or status not in {"ok", "empty", "error"}:
        raise ValueError("invalid_run_status")
    if not isinstance(jobs, list) or len(jobs) > 100 or not isinstance(profiles, list) or len(profiles) > 8:
        raise ValueError("invalid_arrays")
    if (status == "ok" and not jobs) or (status != "ok" and jobs) or (status == "error" and profiles):
        raise ValueError("inconsistent_run_status")
    if not isinstance(payload.get("error", ""), str) or len(payload.get("error", "")) > 1000:
        raise ValueError("invalid_error")
    if status == "error" and not payload.get("error", "").strip():
        raise ValueError("missing_error_description")
    for job in jobs:
        if not isinstance(job, dict) or set(job) - (TEXT_FIELDS | {"score"}):
            raise ValueError("invalid_job_fields")
        if any(not isinstance(job[k], str) or len(job[k]) > 4000 for k in TEXT_FIELDS & job.keys()):
            raise ValueError("invalid_job_text")
        if "score" in job and job["score"] is not None and (type(job["score"]) is not int or not 1 <= job["score"] <= 10):
            raise ValueError("invalid_score")
        if job.get("work_model", "unknown") not in {"unknown", "remote", "hybrid", "onsite"}:
            raise ValueError("invalid_work_model")
        if job.get("availability", "unknown") not in {"unknown", "active", "closed"}:
            raise ValueError("invalid_availability")
        normalize_job(job)
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) - {"company", "description", "products", "source_url", "status"}:
            raise ValueError("invalid_profile_fields")
        if any(not isinstance(v, str) or len(v) > 2000 for v in profile.values()):
            raise ValueError("invalid_profile_text")
        if not profile.get("company") or profile.get("status") not in {"ready", "unknown"}:
            raise ValueError("invalid_profile")
        if profile["status"] == "ready":
            if not profile.get("description") or not profile.get("products"):
                raise ValueError("incomplete_profile")
            canonical_url(profile.get("source_url"))
    if "run_id" in payload and (not isinstance(payload["run_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", payload["run_id"])):
        raise ValueError("invalid_run_id")
    if "ran_at" in payload:
        if not isinstance(payload["ran_at"], str) or len(payload["ran_at"]) > 50:
            raise ValueError("invalid_ran_at")
        stamp = datetime.fromisoformat(payload["ran_at"])
        if stamp.tzinfo is None:
            raise ValueError("ran_at_requires_timezone")
    return payload


def import_file(path: Path) -> dict:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("file_too_large")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("file_too_large")
    digest = hashlib.sha256(raw).hexdigest()
    fallback_id = "file:" + digest
    ran_at = now_iso()
    if path.suffix.lower() == ".md":
        job_id = CONFIG["hermes"]["job_id"]
        if not job_id:
            raise ValueError("hermes_job_id_required_for_markdown")
        fallback_id = "hermes:" + job_id + ":" + path.stem
        if not re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d", path.stem):
            raise ValueError("invalid_hermes_filename")
        stamp = datetime.strptime(path.stem, "%Y-%m-%d_%H-%M-%S")
        ran_at = stamp.replace(tzinfo=ZoneInfo(CONFIG["timezone"])).isoformat()
    elif path.suffix.lower() != ".json":
        raise ValueError("only_json_or_hermes_markdown")
    if has_run(fallback_id):
        return {"already_imported": True, "count": 0}
    try:
        body = raw.decode("utf-8")
        if path.suffix.lower() == ".md":
            marker = "\n## Response\n"
            if marker not in body:
                raise ValueError("response_section_missing")
            body = body.rsplit(marker, 1)[1].strip()
        payload = parse_json_response(body)
        run_id = fallback_id if path.suffix.lower() == ".md" else "json:" + payload.get("run_id", digest)
        if has_run(run_id):
            return {"already_imported": True, "count": 0}
        jobs = [job for job in payload["jobs"] if is_allowed_location(job)]
        result = import_run(run_id, payload.get("ran_at", ran_at), payload["run_status"], jobs,
                            payload.get("error", ""), company_profiles=payload.get("company_profiles", []))
        result["region_filtered"] = len(payload["jobs"]) - len(jobs)
        result["run_status"] = payload["run_status"]
        return result
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        import_run(fallback_id, ran_at, "error", [], "invalid_result")
        raise ValueError("invalid_result") from None


def scan_output() -> dict:
    output = CONFIG["output_path"]
    if not output.is_dir():
        raise ValueError("Hermes-Ausgabeordner fehlt; Konfiguration prüfen")
    summary = {"imported": 0, "errors": 0, "skipped_recent": 0}
    for path in sorted(output.iterdir()):
        if path.suffix.lower() not in {".md", ".json"} or not path.is_file() or path.is_symlink():
            continue
        if time.time() - path.stat().st_mtime < 60:
            summary["skipped_recent"] += 1
            continue
        try:
            result = import_file(path)
            summary["imported"] += result["count"]
            summary["errors"] += int(result.get("run_status") == "error")
        except (OSError, ValueError):
            summary["errors"] += 1
    return summary
