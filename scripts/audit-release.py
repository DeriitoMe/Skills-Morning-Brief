"""Scan staged files, Git history and a ZIP without printing matched secrets."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from morningpaper.core import read_json
from morningpaper.private_store import default_private_root

PATTERNS = (
    re.compile(r"(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"https?://[^\s/]+:[^\s/@]+@"),
)
FORBIDDEN_PARTS = {".runtime", "evidence", "reports", "__pycache__", "node_modules", ".git", "workspaces"}
FORBIDDEN_FILES = {"reader-session.json", "installation.json", "inventory.json", "preferences.json", "feedback.json", "matches.json", "history.json", "state.json", "local-roots.json"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)


def private_values():
    values = [value for key, value in os.environ.items()
              if re.search(r"(?:API_KEY|ACCESS_TOKEN|_TOKEN|_SECRET|_PASSWORD)$", key, re.I) and len(value) >= 8]
    try:
        email = git("config", "--global", "user.email").decode().strip()
        if email and not email.endswith("@users.noreply.github.com"): values.append(email)
    except subprocess.CalledProcessError:
        pass
    store = default_private_root()
    record = read_json(store / "reader-session.json", {})
    values.extend(str(record[key]) for key in ("launch_token", "instance_id") if record.get(key))
    for path in (store / "workspaces").glob("*/profile.json"):
        profile = read_json(path, {})
        values.extend(str(profile[key]) for key in ("id", "name", "goals", "project_directory") if len(str(profile.get(key, ""))) >= 8)
    values.extend((str(Path.home()), str(root)))
    return values


def inspect(name, data, values, paths=True):
    findings = []
    normalized = name.replace("\\", "/")
    parts = set(normalized.split("/"))
    if paths and (parts & FORBIDDEN_PARTS or Path(normalized).name in FORBIDDEN_FILES or "/data/cache/" in "/" + normalized
                  or Path(normalized).name.startswith(".env") and Path(normalized).name != ".env.example"):
        findings.append("private_file")
    content = data.decode("utf-8", errors="replace")
    scan_content = content
    if normalized.endswith("tests/test_sources_and_providers.py"):
        # The endpoint validation test deliberately uses this fixed, non-secret dummy URI.
        # Known real private values are still checked against the original content below.
        dummy_uri = "https://" + "user:password@" + "example.com"
        scan_content = scan_content.replace(dummy_uri, "<dummy-endpoint-test>")
    if any(pattern.search(scan_content) for pattern in PATTERNS): findings.append("credential_pattern")
    if any(value in content or value.replace("\\", "/") in content or json.dumps(value)[1:-1] in content for value in values):
        findings.append("known_private_value")
    return [{"file": name, "kind": kind} for kind in sorted(set(findings))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    if not (args.staged or args.history or args.zip): parser.error("Select --staged, --history or --zip")
    values, findings, counts = private_values(), [], {}
    if args.staged:
        files = [name for name in git("ls-files", "-z").decode().split("\0") if name]
        for name in files: findings.extend(inspect(name, git("show", ":" + name), values))
        counts["staged_files"] = len(files)
    if args.history:
        findings.extend(inspect("commit_metadata", git("log", "--all", "--format=%B%n%an <%ae>%n%cn <%ce>"), values, paths=False))
        objects = git("rev-list", "--objects", "--all").decode().splitlines()
        blobs = 0
        for line in objects:
            oid, _, name = line.partition(" ")
            if git("cat-file", "-t", oid).strip() == b"blob":
                findings.extend(inspect("history:" + name, git("cat-file", "blob", oid), values, paths=False)); blobs += 1
        counts["history_blobs"] = blobs
    if args.zip:
        with zipfile.ZipFile(args.zip) as archive:
            for name in archive.namelist():
                if not name.endswith("/"): findings.extend(inspect(name, archive.read(name), values))
            counts["archive_files"] = len(archive.namelist())
    print(json.dumps({"passed": not findings, "counts": counts, "findings": findings}, ensure_ascii=False))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
