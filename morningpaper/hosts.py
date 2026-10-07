from __future__ import annotations

import os
import platform
from pathlib import Path


HOSTS = {
    "codex": {"label": "Codex", "user": [".agents/skills"], "project": [".agents/skills"]},
    "claude_code": {"label": "Claude Code", "user": [".claude/skills"], "project": [".claude/skills"]},
    "cursor": {"label": "Cursor", "user": [".agents/skills", ".cursor/skills", ".claude/skills", ".codex/skills"], "project": [".agents/skills", ".cursor/skills", ".claude/skills", ".codex/skills"]},
    "deepcode": {"label": "DeepSeek / Deep Code", "user": [".agents/skills"], "project": [".deepcode/skills"]},
    "generic": {"label": "其他 Agent / 通用 Skill 目录", "user": [".agents/skills"], "project": [".agents/skills"]},
}


def project_ancestors(directory):
    current = Path(directory).expanduser().resolve()
    if not current.is_dir():
        raise ValueError("业务工作目录不存在")
    result = [current]
    if (current / ".git").exists():
        return result
    for parent in current.parents:
        result.append(parent)
        if (parent / ".git").exists():
            return result
    return [current]  # no repo found: do not walk the machine's entire parent chain


def discover_roots(host="codex", project_directory="", home=None, codex_home=None):
    if host not in HOSTS:
        raise ValueError("未知的 Agent 工具")
    home = Path(home) if home else Path.home()
    roots = []
    for relative in HOSTS[host]["user"]:
        path = home / relative
        roots.append({"path": str(path), "scope": "user", "label": "用户技能", "exists": path.is_dir()})
    config_path = None
    if host == "codex":
        base = Path(codex_home or os.environ.get("CODEX_HOME") or home / ".codex")
        legacy = base / "skills"
        if legacy.is_dir():
            roots.append({"path": str(legacy), "scope": "user", "label": "Codex 配置中的技能目录", "exists": True})
        config_path = str(base / "config.toml")
        cache = base / "plugins/cache"
        if cache.is_dir():
            for provider in cache.iterdir():
                if not provider.is_dir():
                    continue
                for plugin in provider.iterdir():
                    if not plugin.is_dir():
                        continue
                    versions = [version for version in plugin.iterdir() if version.is_dir() and (version / "skills").is_dir()]
                    if versions:
                        latest = max(versions, key=lambda version: version.stat().st_mtime)
                        roots.append({"path": str(latest / "skills"), "scope": "plugin_cache", "label": "插件缓存 · " + plugin.name + "（启用与连接待确认）", "exists": True})
    if project_directory:
        for ancestor in project_ancestors(project_directory):
            for relative in HOSTS[host]["project"]:
                path = ancestor / relative
                if path.is_dir():
                    roots.append({"path": str(path), "scope": "project", "label": "当前业务项目技能", "exists": True})
    seen, unique = set(), []
    for root in roots:
        identity = os.path.normcase(str(Path(root["path"]).resolve()))
        if identity not in seen:
            unique.append(root)
            seen.add(identity)
    return {"host": host, "host_label": HOSTS[host]["label"], "operating_system": platform.system(), "roots": unique,
            "config_path": config_path, "notes": ["这里只检查确认的 Skill 目录，不执行 Skill 脚本。", "DeepSeek 模型与实际存放 Skills 的 Agent 工具可以分别选择。"]}
