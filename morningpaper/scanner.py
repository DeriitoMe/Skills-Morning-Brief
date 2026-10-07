from __future__ import annotations

import os
import re
import tomllib
from itertools import islice
from pathlib import Path

from .core import capability_tags, fingerprint, frontmatter, now_iso


def scan_roots(roots, host="generic", config_path=None, native_capabilities=None):
    if not roots:
        raise ValueError("请确认至少一个 Skill 目录，或导入能力清单")
    disabled, errors, grouped, paths = set(), [], {}, []
    if host == "codex" and config_path and Path(config_path).is_file():
        try:
            settings = tomllib.loads(Path(config_path).read_text(encoding="utf-8-sig"))
            disabled = {os.path.normcase(str(Path(row["path"]).resolve())) for row in settings.get("skills", {}).get("config", [])
                        if row.get("enabled") is False and row.get("path")}
        except (OSError, ValueError):
            errors.append({"source": "Agent 启用设置", "reason": "读取失败，启用状态待确认"})
    for spec in roots:
        root = Path(spec["path"]).expanduser().resolve()
        if root == Path(root.anchor):
            raise ValueError("请选择具体 Skill 目录，不能选择整个磁盘")
        if not root.is_dir():
            errors.append({"source": spec.get("label", "Skill 目录"), "reason": "目录不存在"})
            continue
        try:
            if any(child.is_symlink() and child.is_dir() for child in root.iterdir()):
                errors.append({"source": spec.get("label", "Skill 目录"), "reason": "目录有链接目标，需确认其真实 Skill 目录后检查"})
            found = list(islice(root.rglob("SKILL.md"), 2001))
            if len(found) > 2000:
                errors.append({"source": spec.get("label", "Skill 目录"), "reason": "文件数量超过本轮限制"})
            paths += [(path, root, spec) for path in found[:2000]]
        except OSError:
            errors.append({"source": spec.get("label", "Skill 目录"), "reason": "没有读取权限"})
    for path, root, spec in paths:
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                errors.append({"source": path.parent.name, "reason": "链接目标超出已确认目录"})
                continue
            if any(part in (".trash", ".git", "node_modules", "fixtures", "tests") for part in path.relative_to(root).parts):
                continue
            if path.stat().st_size > 2_000_000:
                errors.append({"source": path.parent.name, "reason": "定义文件过大，未完整检查"})
                continue
            text = path.read_text(encoding="utf-8-sig")
            meta = frontmatter(text)
            name, description = meta.get("name", ""), meta.get("description", "")
            if host in ("cursor", "claude_code"):
                name = name or path.parent.name
                if not description:
                    body = re.sub(r"^---\s*\n.*?\n---\s*", "", text, flags=re.S)
                    description = " ".join(line.strip(" #-* ") for line in body.splitlines() if line.strip())[:800]
            if not name or not description:
                errors.append({"source": path.parent.name, "reason": "缺少名称或功能说明"})
                continue
            material = fingerprint(text)
            key = (name, material, spec.get("scope", "custom"))
            enabled = os.path.normcase(str(resolved)) not in disabled
            if key in grouped:
                grouped[key]["copies"] += 1
                grouped[key]["enabled"] |= enabled
                continue
            grouped[key] = {"id": fingerprint([name, material, spec.get("scope", "custom")])[:24], "name": name,
                "description": description[:1200], "fingerprint": material, "source_fingerprint": material,
                "tags": capability_tags(name + " " + description), "enabled": enabled, "availability": "needs_runtime_check",
                "scope": spec.get("scope", "custom"), "source": "local_file", "source_label": spec.get("label", "Skill 目录"),
                "copies": 1, "evidence": "已读取定义；账户、依赖与宿主调用未运行验证"}
        except (OSError, UnicodeError):
            errors.append({"source": path.parent.name, "reason": "文件读取失败"})
    skills = sorted(grouped.values(), key=lambda row: (row["name"], row["scope"]))
    inventory = {"schema_version": 2, "host": host, "captured_at": now_iso(), "skills": skills,
                 "native_capabilities": native_capabilities or [], "errors": errors, "scan_status": "partial" if errors else "complete",
                 "scope": "confirmed user/project/plugin/custom roots; runtime dependencies not verified"}
    inventory["version"] = fingerprint({"skills": skills, "native": inventory["native_capabilities"], "host": host})
    return inventory


def import_inventory(value, host="generic"):
    if not isinstance(value, dict) or not isinstance(value.get("skills"), list) or len(value["skills"]) > 2000:
        raise ValueError("导入清单应包含 skills 数组，最多 2000 项")
    skills = []
    for item in value["skills"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("description"), str):
            raise ValueError("每项 Skill 需要 name 和 description")
        name, description = item["name"].strip()[:160], item["description"].strip()[:1200]
        if not name or not description:
            raise ValueError("名称与说明不能为空")
        row = {"id": fingerprint([name, description])[:24], "name": name, "description": description,
               "fingerprint": fingerprint([name, description]), "tags": capability_tags(name + " " + description),
               "enabled": item.get("enabled") is not False, "availability": "needs_runtime_check", "scope": "imported",
               "source": "user_import", "evidence": "用户提供的能力清单，未检查本机文件或运行依赖"}
        for key in ("catalog_skill_id", "catalog_fingerprint", "source_fingerprint"):
            if isinstance(item.get(key), str) and len(item[key]) <= 500:
                row[key] = item[key]
        skills.append(row)
    if not skills and value.get("confirmed_empty") is not True:
        raise ValueError("空清单需要明确设置 confirmed_empty=true")
    return {"schema_version": 2, "host": host, "captured_at": now_iso(), "skills": skills, "native_capabilities": [], "errors": [],
            "scan_status": "imported", "scope": "user-provided inventory", "version": fingerprint([host, skills])}
