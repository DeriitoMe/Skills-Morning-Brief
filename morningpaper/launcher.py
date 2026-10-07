from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .core import ROOT, fingerprint, read_json
from .private_store import PrivateStore


def reader_record(store, project=ROOT):
    record = read_json(store.root / "reader-session.json", {})
    if record.get("instance_id") != store.instance_id:
        return None
    try:
        with urllib.request.urlopen("http://127.0.0.1:" + str(record["port"]) + "/api/instance", timeout=2) as response:
            import json
            identity = json.load(response)
        return record if identity.get("instance_id") == store.instance_id and identity.get("project_id") == fingerprint(str(project.resolve())) else None
    except (OSError, ValueError, KeyError):
        return None


def start_reader(project=ROOT, store=None, open_browser=False):
    store = store or PrivateStore()
    record = reader_record(store, project)
    if not record:
        logs = store.root / "runtime"
        logs.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        environment = {**os.environ, "MORNINGPAPER_DATA_DIR": str(store.root), "PYTHONIOENCODING": "utf-8"}
        with (logs / "reader.log").open("a", encoding="utf-8") as output, (logs / "reader-errors.log").open("a", encoding="utf-8") as errors:
            child = subprocess.Popen([sys.executable, "-m", "morningpaper", "serve"], cwd=project, env=environment,
                             stdin=subprocess.DEVNULL, stdout=output, stderr=errors, creationflags=flags)
        for attempt in range(120):
            time.sleep(.25)
            record = reader_record(store, project)
            if record:
                break
            if child.poll() is not None:
                break
    if not record:
        raise RuntimeError("本机阅读服务未能启动，请检查本机日志")
    url = "http://127.0.0.1:" + str(record["port"])
    if open_browser:
        webbrowser.open(url + "/#session=" + record["launch_token"])
    return url
