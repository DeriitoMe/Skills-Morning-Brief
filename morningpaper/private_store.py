from __future__ import annotations

import os
import platform
import threading
import uuid
from pathlib import Path

from .core import fingerprint, now_iso, read_json, write_json
from .hosts import HOSTS
from .providers import provider_settings


def default_private_root():
    override = os.environ.get("MORNINGPAPER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "AgentSkillShelf"
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/AgentSkillShelf"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "agent-skill-shelf"


class PrivateStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else default_private_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        path = self.root / "installation.json"
        installation = read_json(path)
        if not installation:
            installation = {"instance_id": str(uuid.uuid4()), "created_at": now_iso(), "active_workspace": None}
            write_json(path, installation)
        self.instance_id = installation["instance_id"]

    def workspace_dir(self, workspace_id):
        try:
            canonical = str(uuid.UUID(workspace_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("工作区不存在") from None
        if canonical != workspace_id:
            raise ValueError("工作区不存在")
        path = self.root / "workspaces" / canonical
        profile = read_json(path / "profile.json", {})
        if not profile or profile.get("instance_id") != self.instance_id:
            raise ValueError("工作区不属于当前用户实例")
        return path

    def list_workspaces(self):
        result = []
        for path in (self.root / "workspaces").glob("*/profile.json"):
            row = read_json(path, {})
            if row.get("instance_id") == self.instance_id:
                result.append(row)
        return sorted(result, key=lambda row: row["created_at"])

    def profile(self, workspace_id):
        return read_json(self.workspace_dir(workspace_id) / "profile.json")

    def _normalize(self, value):
        name = str(value.get("name", "我的工作区")).strip()[:80]
        host = value.get("host", "codex")
        if not name or host not in HOSTS:
            raise ValueError("请填写工作区名称并选择 Agent 工具")
        goals = str(value.get("goals", "")).strip()[:2000]
        stack = str(value.get("stack", "")).strip()[:1000]
        roots = []
        for spec in value.get("roots", []):
            if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
                raise ValueError("Skill 目录格式不正确")
            path = Path(spec["path"]).expanduser()
            if not path.is_absolute() or path.resolve() == Path(path.anchor):
                raise ValueError("请选择具体的绝对目录")
            scope = spec.get("scope", "custom")
            if scope not in ("user", "project", "plugin_cache", "custom"):
                raise ValueError("目录作用域不正确")
            roots.append({"path": str(path.resolve()), "scope": scope, "label": str(spec.get("label", "自选技能目录"))[:160]})
        if len(roots) > 80:
            raise ValueError("一次最多检查 80 个技能目录")
        directory = str(value.get("project_directory", "")).strip()[:2000]
        if directory and not Path(directory).is_dir():
            raise ValueError("业务工作目录不存在")
        provider = provider_settings(value.get("provider", {"id": "codex"}))
        inventory_mode = value.get("inventory_mode", "filesystem")
        if inventory_mode not in ("filesystem", "imported"):
            raise ValueError("清单来源模式不正确")
        return {"name": name, "host": host, "goals": goals, "stack": stack, "roots": roots, "project_directory": directory,
                "provider": provider, "inventory_mode": inventory_mode, "automatic_recommendations": value.get("automatic_recommendations") is True,
                "operating_system": platform.system(), "timezone": str(value.get("timezone", "Asia/Shanghai"))[:80]}

    def create_workspace(self, value):
        with self.lock:
            profile = self._normalize(value)
            workspace_id = str(uuid.uuid4())
            profile.update(id=workspace_id, instance_id=self.instance_id, created_at=now_iso(), updated_at=now_iso())
            write_json(self.root / "workspaces" / workspace_id / "profile.json", profile)
            self.set_active(workspace_id)
            return profile

    def update_workspace(self, workspace_id, value):
        with self.lock:
            old = self.profile(workspace_id)
            normalized = self._normalize({**old, **value})
            profile = {**old, **normalized, "updated_at": now_iso()}
            write_json(self.workspace_dir(workspace_id) / "profile.json", profile)
            return profile

    def set_active(self, workspace_id):
        self.workspace_dir(workspace_id)
        with self.lock:
            path = self.root / "installation.json"
            data = read_json(path)
            data["active_workspace"] = workspace_id
            write_json(path, data)

    def active(self):
        return read_json(self.root / "installation.json", {}).get("active_workspace")

    def read(self, workspace_id, filename, default=None):
        if filename not in ("inventory.json", "feedback.json", "matches.json", "history.json", "latest.json", "archive.json"):
            raise ValueError("未知的私人资料类型")
        return read_json(self.workspace_dir(workspace_id) / filename, default)

    def write(self, workspace_id, filename, value):
        if filename not in ("inventory.json", "feedback.json", "matches.json", "history.json", "latest.json", "archive.json"):
            raise ValueError("未知的私人资料类型")
        with self.lock:
            write_json(self.workspace_dir(workspace_id) / filename, value)

    def profile_version(self, profile):
        return fingerprint({key: profile.get(key) for key in ("host", "goals", "stack", "operating_system", "provider")})

    def scan_version(self, profile):
        return fingerprint({key: profile.get(key) for key in ("host", "roots", "project_directory")})
