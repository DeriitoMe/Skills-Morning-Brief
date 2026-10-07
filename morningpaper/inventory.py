from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .core import ROOT, capability_tags, fingerprint, frontmatter, now_iso, read_json, write_json


def scan_inventory(root=ROOT):
    settings = read_json(root / "profile/local-roots.json", {})
    preferences = read_json(root / "profile/preferences.json", {})
    paths, errors = set(), []
    disabled = set()
    config_path = settings.get("config_path")
    if config_path and Path(config_path).exists():
        try:
            config = tomllib.loads(Path(config_path).read_text(encoding="utf-8-sig"))
            for row in config.get("skills", {}).get("config", []):
                if row.get("enabled") is False and row.get("path"):
                    disabled.add(os.path.normcase(str(Path(row["path"]).resolve())))
        except (OSError, ValueError) as exc:
            errors.append({"source": "Codex skill settings", "error": type(exc).__name__})
    for directory in settings.get("user_roots", []):
        if not Path(directory).exists():
            errors.append({"source": "local skill root", "error": "missing"})
            continue
        try:
            paths.update(Path(directory).rglob("SKILL.md"))
        except OSError as exc:
            errors.append({"source": "local skill root", "error": type(exc).__name__})
    for file in settings.get("bundled_skill_paths", []):
        paths.add(Path(file))
    paths.update((root / ".agents/skills").rglob("SKILL.md"))
    grouped = {}
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8-sig")
            meta = frontmatter(text)
            if not meta.get("name") or not meta.get("description"):
                continue
            key = (meta["name"], fingerprint(text))
            enabled = os.path.normcase(str(path.resolve())) not in disabled
            source = "bundled_plugin" if "plugins" in path.parts else "local"
            if key in grouped:
                grouped[key]["copies"] += 1
                grouped[key]["enabled"] |= enabled
                continue
            grouped[key] = {
                "name": meta["name"],
                "description": meta["description"][:1200],
                "fingerprint": key[1],
                "tags": capability_tags(meta["name"] + " " + meta["description"]),
                "enabled": enabled,
                "availability": "needs_runtime_check",
                "source": source,
                "copies": 1,
            }
        except (OSError, UnicodeError) as exc:
            errors.append({"source": path.parent.name, "error": type(exc).__name__})
    inventory = {
        "schema_version": 1,
        "captured_at": now_iso(),
        "skills": sorted(grouped.values(), key=lambda x: x["name"]),
        "native_capabilities": preferences.get("native_capabilities", []),
        "errors": errors,
        "scope": "configured local roots and current bundled skill paths; account connections not verified",
    }
    inventory["version"] = fingerprint(inventory["skills"])
    write_json(root / "profile/inventory.json", inventory)
    rows = ["# Codex 能力清单", "", "采集时间：" + inventory["captured_at"], ""]
    rows += [
        "- " + item["name"] + "：" + item["description"][:140]
        for item in inventory["skills"]
    ]
    (root / "profile/inventory-summary.md").write_text("\n".join(rows), encoding="utf-8")
    return inventory
