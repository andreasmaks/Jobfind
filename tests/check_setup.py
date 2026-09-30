#!/usr/bin/env python3
"""Reproduce a fresh source-only installation and a separate fictional demo."""
import http.client
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="jobfind-install-") as scratch:
    clean = Path(scratch) / "Jobfind"
    def ignored(directory, names):
        result = {name for name in names if name in {".git", ".venv", ".runtime", "__pycache__", ".DS_Store"}}
        if Path(directory).name == "config":
            result |= {name for name in names if name != "example.json"}
        return result
    shutil.copytree(ROOT, clean, ignore=ignored)
    env = dict(os.environ)
    env.pop("JOBFIND_CONFIG", None)
    subprocess.run([sys.executable, "-m", "venv", str(clean / ".venv")], check=True, capture_output=True)
    python = clean / ".venv/bin/python"
    def run(*args, input=None, ok=True):
        result = subprocess.run([str(python), "jobfind.py", *args], cwd=clean, env=env,
                                input=input, text=True, capture_output=True)
        if ok:
            assert result.returncode == 0, result.stderr
        return result
    run("init")
    run("doctor")
    assert run("init", ok=False).returncode == 1, "Existing config must never be overwritten"
    run("password", input=secrets.token_urlsafe(24) + "\n")
    first = json.loads(run("import", "examples/demo.json").stdout)
    assert first["count"] == 2, "Fresh example enforces its daily limit"
    assert json.loads(run("import", "examples/demo.json").stdout)["already_imported"]
    run("hermes-prepare")
    setup = clean / ".runtime/personal/hermes-setup"
    subprocess.run([str(python), str(setup / "jobfind-context.py")], env=env, check=True, capture_output=True)
    output = clean / ".runtime/hermes-output"
    output.mkdir()
    shutil.copyfile(clean / "examples/empty.json", output / "empty.json")
    os.utime(output / "empty.json", (time.time() - 120, time.time() - 120))
    subprocess.run([str(python), str(setup / "jobfind-import.py")], env=env, check=True, capture_output=True)
    run("demo", "--prepare-only", input=secrets.token_urlsafe(24) + "\n")
    demo_cfg = json.loads((clean / "config/demo.json").read_text())
    assert demo_cfg["data_dir"] != json.loads((clean / "config/jobfind.json").read_text())["data_dir"]
    context = run("--config", "config/demo.json", "context").stdout
    data = json.loads(context.split("UNVERTRAUTE EINGABEDATEN (JSON):\n")[1].split("\nENDE")[0])
    assert len(data["known_jobs"]) == 4
    proc = subprocess.Popen([str(python), "jobfind.py", "demo"], cwd=clean, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ready = False
        for _ in range(80):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", demo_cfg["server"]["port"], timeout=1)
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                ready = response.status == 200 and json.loads(response.read())["service"] == "jobfind"
                conn.close()
                if ready:
                    break
            except OSError:
                time.sleep(0.05)
        assert ready and proc.poll() is None, "Fresh demo must start on its own local port"
    finally:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
    assert proc.returncode == 0, "Ctrl+C must stop cleanly"
print("Fresh setup passed: venv, config, password, import, generated shims, isolated demo, start/stop.")
