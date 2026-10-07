from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import threading
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalog import catalog_public, evaluate_catalog, prepare_catalog
from .core import ROOT, fingerprint, now_iso, read_json, write_json
from .hosts import HOSTS, discover_roots
from .personal import board_for_workspace, generate_personal, import_workspace_inventory, scan_workspace
from .private_store import PrivateStore
from .providers import PROVIDERS, ProviderError, provider_identity


class LocalHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ShelfService:
    def __init__(self, project=ROOT, store=None):
        self.project = Path(project)
        self.store = store or PrivateStore()
        self.launch_token = secrets.token_urlsafe(32)
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.jobs, self.keys = {}, {}
        self.lock = threading.RLock()
        self.catalog_lock = threading.Lock()
        if not read_json(self.project / "data/public/catalog.json"):
            from .runner import run_lock
            with run_lock(self.project):
                prepare_catalog(self.project)

    def start_job(self, action, workspace_id, limit=18):
        profile = self.store.profile(workspace_id)
        if action not in ("scan", "recommend", "catalog"):
            raise ValueError("未知的任务类型")
        with self.lock:
            if any(job["status"] == "running" and job["workspace_id"] == workspace_id for job in self.jobs.values()):
                raise ValueError("这个工作区已有任务在运行")
            job_id = str(uuid.uuid4())
            job = {"id": job_id, "workspace_id": workspace_id, "action": action, "status": "running", "done": 0, "total": 0, "message": "正在准备", "created_at": now_iso()}
            self.jobs[job_id] = job

        def progress(done, total):
            with self.lock:
                job.update(done=done, total=total, message="已完成 " + str(done) + " / " + str(total))

        def work():
            try:
                if action == "scan":
                    inventory = scan_workspace(self.store, workspace_id)
                    progress(len(inventory["skills"]), len(inventory["skills"]))
                    job["message"] = "已检查 " + str(len(inventory["skills"])) + " 个 Skill；依赖未运行验证"
                elif action == "catalog":
                    from .runner import run_lock
                    with self.catalog_lock, run_lock(self.project):
                        catalog = read_json(self.project / "data/public/catalog.json")
                        evaluate_catalog(catalog, profile["provider"], self.store.root / "runtime/catalog", self.project, limit, progress, self.keys.get((workspace_id, provider_identity(profile["provider"]))))
                else:
                    generate_personal(self.store, workspace_id, self.project, limit, progress, self.keys.get((workspace_id, provider_identity(profile["provider"]))))
                with self.lock:
                    job.update(status="complete", completed_at=now_iso())
            except (ProviderError, ValueError, RuntimeError) as exc:
                with self.lock:
                    job.update(status="failed", message=str(exc)[:500], completed_at=now_iso())
            except OSError:
                with self.lock:
                    job.update(status="failed", message="本机文件操作失败，请检查目录与权限", completed_at=now_iso())
            except Exception:
                with self.lock:
                    job.update(status="failed", message="任务异常中断，已完成的数据仍保留，请重新尝试", completed_at=now_iso())
            write_json(self.store.workspace_dir(workspace_id) / "jobs" / (job_id + ".json"), job)

        threading.Thread(target=work, daemon=True).start()
        return dict(job)


def make_shelf_handler(service, port):
    allowed_host = "127.0.0.1:" + str(port)
    cookie_name = "skill_shelf_session_" + str(port)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, status, value, kind="application/json; charset=utf-8", cookie=None):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            if self.headers.get("Host") != allowed_host:
                self.send(403, {"error": "只接受本机地址访问"})
                return False
            return True

        def authenticated(self):
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                value = cookies.get(cookie_name)
                valid = value and hmac.compare_digest(value.value, service.session_token)
            except Exception:
                valid = False
            if not valid:
                self.send(401, {"error": "请从本机启动器打开你的私人陈列库", "needs_session": True})
                return False
            return True

        def workspace_id(self, value=None):
            query = parse_qs(urlparse(self.path).query)
            workspace_id = self.headers.get("X-Workspace-Id") or query.get("workspace_id", [None])[0] or (value or {}).get("workspace_id") or service.store.active()
            if not workspace_id:
                raise ValueError("请先创建自己的工作区")
            service.store.workspace_dir(workspace_id)
            return workspace_id

        def do_GET(self):
            if not self.valid_host():
                return
            path = urlparse(self.path).path
            if path == "/api/instance":
                return self.send(200, {"instance_id": service.store.instance_id, "project_id": fingerprint(str(service.project.resolve())), "version": "1.0.0"})
            files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/onboarding.js": ("onboarding.js", "text/javascript; charset=utf-8"), "/onboarding.css": ("onboarding.css", "text/css; charset=utf-8"),
                     "/home.css": ("home.css", "text/css; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8"), "/readability.css": ("readability.css", "text/css; charset=utf-8"),
                     "/vendor/gsap.min.js": ("vendor/gsap.min.js", "text/javascript; charset=utf-8"),
                     "/vendor/ScrollTrigger.min.js": ("vendor/ScrollTrigger.min.js", "text/javascript; charset=utf-8")}
            if path in files:
                name, kind = files[path]
                file = service.project / "web" / name
                return self.send(200, file.read_bytes(), kind) if file.exists() else self.send(404, {"error": "资源不存在"})
            if path == "/api/public/home":
                from .public_monitor import public_home
                return self.send(200, public_home(service.project))
            if path in ("/api/public/catalog", "/api/catalog"):
                return self.send(200, catalog_public(read_json(service.project / "data/public/catalog.json", {})))
            if not self.authenticated():
                return
            try:
                if path == "/api/bootstrap":
                    workspaces = service.store.list_workspaces()
                    active = service.store.active()
                    feedback = service.store.read(active, "feedback.json", {}) if active else {}
                    try:
                        from .editor import codex_binary
                        codex_available = bool(codex_binary())
                    except RuntimeError:
                        codex_available = False
                    provider_status = {key: {"label": value["label"], "configured": codex_available if key == "codex" else bool(os.environ.get(value.get("api_key_env", "")))} for key, value in PROVIDERS.items()}
                    return self.send(200, {"token": service.csrf_token, "instance_id": service.store.instance_id, "workspaces": workspaces,
                                          "active_workspace": active, "onboarding": not workspaces, "feedback": feedback, "hosts": HOSTS, "providers": provider_status})
                if path == "/api/catalog":
                    return self.send(200, catalog_public(read_json(service.project / "data/public/catalog.json", {})))
                if path == "/api/discover":
                    query = parse_qs(urlparse(self.path).query)
                    return self.send(200, discover_roots(query.get("host", ["codex"])[0], query.get("project_directory", [""])[0]))
                if path == "/api/jobs":
                    workspace_id = self.workspace_id()
                    return self.send(200, [job for job in service.jobs.values() if job["workspace_id"] == workspace_id])
                workspace_id = self.workspace_id()
                if path == "/data/leaderboard.json":
                    return self.send(200, board_for_workspace(service.store, workspace_id, service.project))
                if path == "/data/inventory.json":
                    return self.send(200, service.store.read(workspace_id, "inventory.json", {"skills": [], "native_capabilities": [], "needs_scan": True}))
                if path == "/data/latest.json":
                    report = service.store.read(workspace_id, "latest.json")
                    return self.send(200, report) if report else self.send(404, {"error": "这个工作区尚未生成晨报"})
                if path == "/data/archive.json":
                    return self.send(200, service.store.read(workspace_id, "archive.json", []))
                if path == "/api/feedback":
                    return self.send(200, service.store.read(workspace_id, "feedback.json", {}))
                if path == "/api/saved":
                    feedback = service.store.read(workspace_id, "feedback.json", {})
                    board = board_for_workspace(service.store, workspace_id, service.project)
                    return self.send(200, [row for row in board["items"] if feedback.get(row["id"], {}).get("action") == "interested"])
                if path.startswith("/api/report/"):
                    report_id = path.removeprefix("/api/report/")
                    archive = service.store.read(workspace_id, "archive.json", [])
                    if report_id in {row["id"] for row in archive}:
                        return self.send(200, read_json(service.store.workspace_dir(workspace_id) / "reports" / (report_id + ".json")))
                self.send(404, {"error": "资源不存在"})
            except ValueError as exc:
                self.send(400, {"error": str(exc)})

        def do_POST(self):
            if not self.valid_host():
                return
            if self.headers.get("Origin") not in (None, "http://" + allowed_host):
                return self.send(403, {"error": "请求来源无效"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2_000_000:
                    return self.send(400, {"error": "请求大小不正确"})
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError("请求格式不正确")
                path = urlparse(self.path).path
                if path == "/api/session":
                    token = value.get("launch_token", "")
                    if not isinstance(token, str) or not hmac.compare_digest(token, service.launch_token):
                        return self.send(403, {"error": "本机启动会话无效"})
                    cookie = cookie_name + "=" + service.session_token + "; HttpOnly; SameSite=Strict; Path=/"
                    return self.send(200, {"ok": True}, cookie=cookie)
                if not self.authenticated():
                    return
                if self.headers.get("X-Morningpaper-Token") != service.csrf_token:
                    return self.send(403, {"error": "操作会话无效"})
                if path == "/api/workspaces":
                    profile = service.store.create_workspace(value)
                    if value.get("session_api_key"):
                        service.keys[(profile["id"], provider_identity(profile["provider"]))] = str(value["session_api_key"])[:1000]
                    return self.send(201, profile)
                workspace_id = self.workspace_id(value)
                if path == "/api/workspace/select":
                    service.store.set_active(workspace_id)
                    return self.send(200, service.store.profile(workspace_id))
                if path == "/api/workspace/update":
                    if any(job["status"] == "running" and job["workspace_id"] == workspace_id for job in service.jobs.values()):
                        return self.send(409, {"error": "这个工作区的任务还在运行，完成后再修改工具和模型"})
                    profile = service.store.update_workspace(workspace_id, value)
                    if value.get("session_api_key"):
                        service.keys[(workspace_id, provider_identity(profile["provider"]))] = str(value["session_api_key"])[:1000]
                    return self.send(200, profile)
                if path == "/api/inventory/import":
                    if any(job["status"] == "running" and job["workspace_id"] == workspace_id for job in service.jobs.values()):
                        return self.send(409, {"error": "这个工作区的任务还在运行，完成后再导入清单"})
                    return self.send(200, import_workspace_inventory(service.store, workspace_id, value.get("inventory")))
                if path == "/api/jobs":
                    limit = int(value.get("limit", 18))
                    if not 1 <= limit <= 120:
                        raise ValueError("分析数量应在 1–120 之间")
                    if value.get("session_api_key"):
                        profile = service.store.profile(workspace_id)
                        service.keys[(workspace_id, provider_identity(profile["provider"]))] = str(value["session_api_key"])[:1000]
                    return self.send(202, service.start_job(value.get("action"), workspace_id, limit))
                if path == "/api/feedback":
                    candidate_id, action = value.get("id"), value.get("action")
                    catalog = read_json(service.project / "data/public/catalog.json", {})
                    if action not in ("interested", "not_relevant", "already_have", "reset") or candidate_id not in {row["id"] for row in catalog.get("items", [])}:
                        raise ValueError("反馈内容不正确")
                    with service.store.lock:
                        feedback = service.store.read(workspace_id, "feedback.json", {})
                        if action == "reset":
                            feedback.pop(candidate_id, None)
                        else:
                            feedback[candidate_id] = {"action": action, "updated_at": now_iso()}
                        service.store.write(workspace_id, "feedback.json", feedback)
                    return self.send(200, {"ok": True, "feedback": feedback})
                self.send(404, {"error": "接口不存在"})
            except (ValueError, TypeError, KeyError) as exc:
                self.send(400, {"error": "输入格式不正确" if isinstance(exc, (TypeError, KeyError)) else str(exc)[:300]})
            except OSError:
                self.send(500, {"error": "本机资料写入失败，请检查权限"})

    return Handler


def serve_shelf(project=ROOT, port=8765, store=None):
    service = ShelfService(project, store)
    server = None
    for candidate in range(port, port + 20):
        try:
            server = LocalHTTPServer(("127.0.0.1", candidate), make_shelf_handler(service, candidate))
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("没有可用的本机阅读端口")
    record = {"instance_id": service.store.instance_id, "port": server.server_port, "pid": os.getpid(), "launch_token": service.launch_token}
    write_json(service.store.root / "reader-session.json", record)
    print("Skills Morning Brief：http://127.0.0.1:" + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
