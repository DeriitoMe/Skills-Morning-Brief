from __future__ import annotations

from datetime import datetime
import re
from pathlib import PurePosixPath

from .collect import is_skill_path
from .core import ROOT, capability_tags, fingerprint, frontmatter, read_json, write_json


def import_snapshots(path, root=ROOT):
    """Import public resources fetched through the connected GitHub plugin."""
    payload = read_json(path)
    if payload.get("provider") != "GitHub plugin":
        raise ValueError("快照来源标记不匹配")
    state = read_json(root / "data/state.json", {"schema_version": 1})
    results = []
    for snapshot in payload["snapshots"]:
        repository, metadata = snapshot["repository"], snapshot["metadata"]
        if repository != metadata["full_name"] or metadata.get("private") or snapshot["tree"].get("truncated"):
            raise ValueError("仓库或目录快照无效")
        commit = snapshot["commit_sha"]
        if len(commit) not in (40, 64) or not re.fullmatch(r"[0-9a-fA-F]+", commit):
            raise ValueError("commit 无效")
        captured = snapshot["captured_at"].replace(" UTC", "+00:00").replace(" ", "T", 1)
        checked = datetime.fromisoformat(captured)
        if checked.tzinfo is None:
            raise ValueError("采集时间必须包含时区")
        blobs = {row["path"]: row for row in snapshot["tree"]["tree"] if row.get("type") == "blob" and row.get("mode") != "120000"}
        previous = state.setdefault("repositories", {}).get(repository, {})
        candidates = {name: dict(row) for name, row in previous.get("candidates", {}).items()
                      if name in blobs and is_skill_path(name)}
        for name, row in candidates.items():
            prefix = str(PurePosixPath(name).parent) + "/"
            current_hash = fingerprint({key: value["sha"] for key, value in blobs.items() if key.startswith(prefix)})
            if current_hash != row.get("fingerprint"):
                row["source_status"] = "pending_refresh"
        count, failures = 0, []
        for source in snapshot["skills"]:
            path, text = source["path"], source["text"]
            if path not in blobs or not is_skill_path(path) or len(text.encode("utf-8")) > 100_000:
                failures.append(path)
                continue
            meta = frontmatter(text)
            if not meta.get("name") or not meta.get("description"):
                failures.append(path)
                continue
            prefix = str(PurePosixPath(path).parent) + "/"
            dependencies = {name: row["sha"] for name, row in blobs.items() if name.startswith(prefix)}
            old = candidates.get(path)
            material_hash = fingerprint(dependencies)
            candidates[path] = {
                "id": str(metadata["id"]) + ":" + path, "name": meta["name"], "description": meta["description"][:1200],
                "repository": repository, "repo_id": metadata["id"], "path": path,
                "url": "https://github.com/" + repository + "/blob/" + commit + "/" + path,
                "repository_url": metadata["html_url"], "stars": metadata["stargazers_count"], "stars_delta_7d": None,
                "collected_at": checked.isoformat(), "first_seen_at": old.get("first_seen_at") if old else checked.isoformat(),
                "fingerprint": material_hash, "source_fingerprint": fingerprint(text), "blob_sha": blobs[path]["sha"],
                "commit_sha": commit, "source_status": "current", "source_provider": "GitHub plugin",
                "previous_fingerprint": old.get("fingerprint") if old and old["fingerprint"] != material_hash else None,
                "previous_description": old.get("description") if old and old["fingerprint"] != material_hash else None,
                "official": repository in ("openai/plugins", "anthropics/skills", "github/awesome-copilot"),
                "tags": capability_tags(meta["name"] + " " + meta["description"]), "compatibility": meta.get("compatibility", ""),
                "license": meta.get("license", "待核对具体 Skill 的许可"), "allowed_tools": meta.get("allowed-tools", ""),
                "source_text": text[:16000], "source_text_truncated": len(text) > 16000,
                "dependency_paths": list(dependencies)[:100], "dependency_review": "仅核对文件路径与指纹，未执行或逐个审查脚本",
                "event_kind": "updated" if old and old["fingerprint"] != material_hash else "first_discovered",
            }
            count += 1
        for row in candidates.values():
            row["stars"] = metadata["stargazers_count"]
        total = sum(is_skill_path(name) for name in blobs)
        snapshots = dict(previous.get("star_snapshots", {}))
        snapshots[checked.date().isoformat()] = metadata["stargazers_count"]
        state["repositories"][repository] = {**previous, "repo_id": metadata["id"], "tree_sha": snapshot["tree"]["sha"],
            "commit_sha": commit, "stars": metadata["stargazers_count"], "skill_count": total, "checked_at": checked.isoformat(),
            "candidates": candidates, "pending_files": max(0, total - len(candidates)), "star_snapshots": snapshots,
            "source_provider": "GitHub plugin"}
        results.append({"repository": repository, "imported": count, "failures": failures, "known": len(candidates), "discovered": total})
    write_json(root / "data/state.json", state)
    return results
