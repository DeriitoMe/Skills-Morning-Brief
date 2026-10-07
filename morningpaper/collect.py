from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from .core import ROOT, capability_tags, fingerprint, frontmatter, inventory_tags, now_iso, read_json, write_json
from .network import urlopen


class CollectionError(RuntimeError):
    pass


class HttpClient:
    def __init__(self, root=ROOT, budget=48, timeout=20):
        self.root = root
        self.budget = budget
        self.timeout = timeout
        self.requests = 0
        self.last_search = 0.0
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        # Reuse the current user's explicit GitHub CLI login without persisting its token.
        if not self.token and shutil.which("gh"):
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                        capture_output=True, text=True, timeout=5, creationflags=flags)
                if result.returncode == 0 and result.stdout.strip():
                    self.token = result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass

    def get(self, url, use_cache=True):
        is_api = urllib.parse.urlparse(url).hostname == "api.github.com"
        if is_api and self.requests >= self.budget:
            raise CollectionError("本次 GitHub 请求预算已用完，余项下次继续")
        if is_api and "/search/" in url:
            pause = 7 - (time.monotonic() - self.last_search)
            if pause > 0:
                time.sleep(pause)
            self.last_search = time.monotonic()
        cache_path = self.root / "data/cache/http" / (fingerprint(url) + ".json")
        cached = read_json(cache_path, {}) if use_cache else {}
        headers = {"User-Agent": "skills-morning-brief/1.0.0", "Accept": "application/vnd.github+json"}
        if is_api and self.token:
            headers["Authorization"] = "Bearer " + self.token
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        for attempt in range(2):
            if is_api:
                if self.requests >= self.budget:
                    raise CollectionError("本次 GitHub 请求预算已用完，余项下次继续")
                self.requests += 1
            try:
                request = urllib.request.Request(url, headers=headers)
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(8_000_001)
                    if len(raw) > 8_000_000:
                        raise CollectionError("响应超过大小限制")
                    text = raw.decode("utf-8")
                    etag = response.headers.get("ETag")
                if use_cache:
                    write_json(cache_path, {"text": text, "etag": etag, "captured_at": now_iso()})
                return json.loads(text) if is_api else text
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and cached.get("text") is not None:
                    text = cached["text"]
                    return json.loads(text) if is_api else text
                if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                    retry_after = exc.headers.get("Retry-After", "2")
                    time.sleep(min(10, int(retry_after) if retry_after.isdigit() else 2))
                    continue
                if exc.code in (403, 429):
                    raise CollectionError("GitHub 访问限制或限流；等待下一轮补查") from None
                raise CollectionError("HTTP " + str(exc.code)) from None
            except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise CollectionError("网络或响应解析失败") from None
        raise CollectionError("请求未完成")

    def api(self, path, params=None):
        url = "https://api.github.com" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.get(url)


def _tree(client, repository, branch):
    result = client.api("/repos/" + repository + "/git/trees/" + urllib.parse.quote(branch, safe=""), {"recursive": "1"})
    if result.get("truncated"):
        raise CollectionError("仓库目录结果被截断，暂不把它记为完成")
    return result


def is_skill_path(path):
    parts = PurePosixPath(path).parts
    return PurePosixPath(path).name == "SKILL.md" and not ({"fixtures", "tests", "test", "template", "templates", "examples", "node_modules", ".git"} & set(parts))


def _skill_priority(path, covered):
    tags = set(capability_tags(path.replace("/", " ").replace("-", " ")))
    value = 30 if tags - covered else 0
    if tags and tags <= covered:
        value -= 20
    for keyword in ("audit", "security", "review", "testing", "eval", "context", "memory", "rag", "mcp"):
        if keyword in path.lower():
            value += 5
    return value


def discover(client, config, state, statuses):
    discovered = {name: row for name, row in state.get("discovered_repositories", {}).items()
                  if row.get("verified_public") is True}
    for query in config["collection"]["discovery_queries"]:
        key = "GitHub 发现：" + query
        try:
            result = client.api("/search/repositories", {"q": query + " is:public", "sort": "stars", "order": "desc", "per_page": 12})
            for row in result.get("items", []):
                if row.get("private") is not False or row.get("visibility", "public") != "public" or row.get("fork") or row.get("archived"):
                    continue
                discovered[row["full_name"]] = {"name": row["full_name"], "priority": 40, "stars": row["stargazers_count"], "verified_public": True}
            statuses.append({
                "source": key,
                "status": "partial" if result.get("incomplete_results") or result.get("total_count", 0) > 12 else "ok",
                "detail": "按热度读取最多 12 项，属于有界发现",
                "checked_at": now_iso(),
            })
        except CollectionError as exc:
            statuses.append({"source": key, "status": "failed", "detail": str(exc), "checked_at": now_iso()})
    state["discovered_repositories"] = discovered
    seeds = config["repositories"]
    seed_names = {item["name"] for item in seeds}
    pool = seeds[2:] + [row for name, row in sorted(discovered.items()) if name not in seed_names]
    maximum = config["collection"]["max_repositories"]
    selected = seeds[:min(2, maximum)]
    slots = maximum - len(selected)
    if pool and slots:
        offset = state.get("rotation_cursor", 0) % len(pool)
        rotated = pool[offset:] + pool[:offset]
        selected += rotated[:slots]
        state["rotation_cursor"] = (offset + slots) % len(pool)
    return selected


def collect_repository(client, spec, state, inventory, config):
    repository = spec["name"]
    repo = client.api("/repos/" + repository)
    if repo.get("private") or repo.get("visibility", "public") != "public":
        raise CollectionError("私人仓库不进入公共 Skill 目录")
    if repo.get("archived"):
        raise CollectionError("仓库已归档，保留为参考资料")
    if not spec.get("official") and repo["stargazers_count"] < config["collection"]["observation_stars"]:
        return [], {"source": repository, "status": "filtered", "detail": "低于观察门槛", "checked_at": now_iso()}
    previous = state.setdefault("repositories", {}).get(repository, {})
    branch = client.api("/repos/" + repository + "/branches/" + urllib.parse.quote(repo["default_branch"], safe=""))
    commit_sha = branch["commit"]["sha"]
    tree = _tree(client, repository, commit_sha)
    blobs = [row for row in tree.get("tree", []) if row.get("type") == "blob" and row.get("mode") != "120000"]
    skill_files = [row for row in blobs if is_skill_path(row["path"])]
    snapshots = dict(previous.get("star_snapshots", {}))
    today = datetime.now(timezone.utc).date()
    previous_week = snapshots.get((today - timedelta(days=7)).isoformat())
    snapshots[today.isoformat()] = repo["stargazers_count"]
    observations = list(previous.get("star_observations", []))
    observations.append({"captured_at": now_iso(), "stars": repo["stargazers_count"]})
    snapshots = {day: count for day, count in snapshots.items() if day >= (today - timedelta(days=45)).isoformat()}
    cached_items = previous.get("candidates", {})
    pending, current = [], {}
    for row in skill_files:
        folder = str(PurePosixPath(row["path"]).parent)
        prefix = "" if folder == "." else folder + "/"
        dependencies = {
            blob["path"]: blob["sha"] for blob in blobs
            if (not prefix or blob["path"].startswith(prefix))
        }
        material_hash = fingerprint(dependencies)
        old = cached_items.get(row["path"])
        if old and old.get("fingerprint") == material_hash:
            current[row["path"]] = old
        else:
            pending.append((row, material_hash, dependencies, old))
            if old:
                current[row["path"]] = {**old, "source_status": "pending_refresh"}
    covered = inventory_tags(inventory)
    priority_names = set(config.get("leaderboard", {}).get("priority_names", []))
    pending.sort(key=lambda item: (PurePosixPath(item[0]["path"]).parent.name not in priority_names, -_skill_priority(item[0]["path"], covered), item[0]["path"]))
    limit = config["collection"]["max_new_files_per_repository"]
    failures = []
    for row, material_hash, dependencies, old in pending[:limit]:
        try:
            blob = client.api("/repos/" + repository + "/git/blobs/" + row["sha"])
            if blob.get("encoding") != "base64":
                raise CollectionError("不支持的文件编码")
            raw = base64.b64decode(blob["content"], validate=False)
            if len(raw) > 100_000:
                raise CollectionError("Skill 文件超过研究大小限制")
            text = raw.decode("utf-8-sig")
            meta = frontmatter(text)
            if not meta.get("name") or not meta.get("description"):
                failures.append({"path": row["path"], "reason": "缺少 name 或 description"})
                continue
            candidate_id = str(repo["id"]) + ":" + row["path"]
            current[row["path"]] = {
                "id": candidate_id,
                "name": meta["name"],
                "description": meta["description"][:1200],
                "repository": repository,
                "repo_id": repo["id"],
                "path": row["path"],
                "url": "https://github.com/" + repository + "/blob/" + commit_sha + "/" + urllib.parse.quote(row["path"]),
                "commit_sha": commit_sha,
                "source_status": "current",
                "repository_url": repo["html_url"],
                "stars": repo["stargazers_count"],
                "stars_delta_7d": None if previous_week is None else repo["stargazers_count"] - previous_week,
                "collected_at": now_iso(),
                "first_seen_at": old.get("first_seen_at") if old else now_iso(),
                "fingerprint": material_hash,
                "blob_sha": row["sha"],
                "previous_fingerprint": old.get("fingerprint") if old else None,
                "previous_description": old.get("description") if old else None,
                "official": bool(spec.get("official")),
                "tags": capability_tags(meta["name"] + " " + meta["description"]),
                "compatibility": meta.get("compatibility", ""),
                "license": meta.get("license", "待核对具体 Skill 的许可"),
                "allowed_tools": meta.get("allowed-tools", ""),
                "source_text": text[:16000],
                "source_fingerprint": fingerprint(text),
                "source_text_truncated": len(text) > 16000,
                "dependency_paths": list(dependencies)[:100],
                "dependency_review": "仅核对文件路径与指纹，未执行或逐个审查脚本",
                "event_kind": "updated" if old else "first_discovered",
            }
        except (CollectionError, UnicodeError, ValueError) as exc:
            failures.append({"path": row["path"], "reason": str(exc)[:150]})
            if old:
                current[row["path"]] = {**old, "source_status": "pending_refresh"}
    remaining = max(0, len(pending) - limit) + len(failures)
    state["repositories"][repository] = {
        "repo_id": repo["id"],
        "tree_sha": tree["sha"],
        "commit_sha": commit_sha,
        "stars": repo["stargazers_count"],
        "star_observations": observations[-180:],
        "stars_captured_at": observations[-1]["captured_at"],
        "skill_count": len(skill_files),
        "checked_at": now_iso(),
        "last_complete_at": previous.get("last_complete_at") if remaining else now_iso(),
        "star_snapshots": snapshots,
        "candidates": current,
        "pending_files": remaining,
    }
    candidates = [
        {**row, "stars": repo["stargazers_count"],
         "stars_delta_7d": None if previous_week is None else repo["stargazers_count"] - previous_week}
        for row in current.values()
    ]
    status = {
        "source": repository, "status": "partial" if remaining else "ok",
        "detail": "发现 " + str(len(skill_files)) + " 个 Skill；已读取 " + str(len(current)) + " 个；待续 " + str(remaining) + " 个",
        "checked_at": now_iso(), "failures": failures,
    }
    return candidates, status


def collect_feed(client, spec, state):
    url = spec["url"]
    request_url = url + ".md" if spec["kind"] == "official_docs" else url
    text = client.get(request_url)
    previous = state.setdefault("feeds", {}).get(url, {})
    current_hash = fingerprint(text)
    rows = []
    if spec["kind"] == "atom":
        xml = ET.fromstring(text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in xml.findall("a:entry", ns)[:4]:
            link = entry.find("a:link", ns)
            item_url = link.attrib.get("href", url) if link is not None else url
            title = entry.findtext("a:title", "", ns)
            published = entry.findtext("a:updated", "", ns)
            content = entry.findtext("a:content", "", ns)
            rows.append({
                "id": fingerprint(item_url), "title": title, "url": item_url,
                "published_at": published or None,
                "source_text": content[:6000], "fingerprint": fingerprint(title + content),
                "source": spec["name"], "first_discovered": not previous,
            })
    elif current_hash != previous.get("fingerprint"):
        start = text.find("# What's new")
        excerpt = text[start if start >= 0 else 0:][:12000]
        rows.append({
            "id": fingerprint(url), "title": spec["name"], "url": url,
            "published_at": None, "source_text": excerpt,
            "fingerprint": current_hash, "source": spec["name"], "first_discovered": not previous,
        })
    state["feeds"][url] = {"fingerprint": current_hash, "last_success_at": now_iso()}
    return rows


def collect(config, inventory, state, root=ROOT, discover_new=True):
    options = config["collection"]
    client = HttpClient(root, options["request_budget"], options["request_timeout_seconds"])
    statuses, candidates, news = [], [], []
    repositories = discover(client, config, state, statuses) if discover_new else config["repositories"][:options["max_repositories"]]
    for spec in repositories:
        try:
            rows, status = collect_repository(client, spec, state, inventory, config)
            candidates += rows
            statuses.append(status)
        except (CollectionError, KeyError, ValueError) as exc:
            statuses.append({"source": spec["name"], "status": "failed", "detail": str(exc)[:180], "checked_at": now_iso()})
    for spec in config.get("feeds", []):
        try:
            news += collect_feed(client, spec, state)
            statuses.append({"source": spec["name"], "status": "ok", "detail": "已检查官方来源", "checked_at": now_iso()})
        except (CollectionError, ET.ParseError) as exc:
            statuses.append({"source": spec["name"], "status": "failed", "detail": str(exc)[:180], "checked_at": now_iso()})
    return candidates, news, statuses, client.requests
