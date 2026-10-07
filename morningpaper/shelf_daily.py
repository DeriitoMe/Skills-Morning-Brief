from __future__ import annotations

import tomllib

from .catalog import prepare_catalog, evaluate_catalog
from .collect import collect
from .core import ROOT, now_iso, read_json, write_json
from .personal import generate_personal, scan_workspace
from .private_store import PrivateStore


def refresh_all(root=ROOT, store=None, personal=True):
    from .runner import run_lock
    started = now_iso()
    with run_lock(root):
        try:
            result = _refresh_all(root, store, personal)
        except Exception as exc:
            record = {"started_at": started, "completed_at": now_iso(), "status": "failed", "error_type": type(exc).__name__}
            _record_run(root, record)
            raise
        failures = any(row.get("status") == "failed" for row in result["sources"] + result["news_sources"])
        record = {"started_at": started, "completed_at": now_iso(),
                  "status": "degraded" if failures or result["public_editor"] == "pending" else "ok",
                  "sources": result["sources"], "news_sources": result["news_sources"], "requests": result["requests"],
                  "public_editor": result["public_editor"], "public_news": result["public_news"],
                  "personal_workspaces_processed": len(result["workspaces"])}
        _record_run(root, record)
        return {**result, "status": record["status"], "completed_at": record["completed_at"]}


def _record_run(root, record):
    write_json(root / ".runtime/latest-monitor.json", record)
    write_json(root / ".runtime/monitor-runs" / (record["started_at"].replace(":", "-") + ".json"), record)


def _refresh_all(root=ROOT, store=None, personal=True):
    store = store or PrivateStore()
    config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8-sig"))
    prepare_catalog(root)
    public_path = root / "data/public/collection.json"
    public = read_json(public_path, {})
    candidates, news, statuses, requests = collect(config, {"skills": [], "native_capabilities": []}, public, root)
    write_json(public_path, public)
    # Feed the catalog builder only public collection facts; there is no workspace history here.
    catalog = prepare_catalog(root, public_state=public)
    import os
    neutral_status = "cached"
    try:
        provider = {"id": "deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "codex"}
        evaluate_catalog(catalog, provider, root / ".runtime/public-editor", root, limit=config["collection"]["max_candidates_for_editor"])
        neutral_status = "ok"
    except (RuntimeError, ValueError, OSError):
        neutral_status = "pending"
    from .public_news import refresh_public_news
    public_news = refresh_public_news(root)
    results = []
    for profile in store.list_workspaces() if personal else []:
        if profile.get("automatic_recommendations") is not True:
            continue
        try:
            if profile["roots"] and profile.get("inventory_mode", "filesystem") == "filesystem":
                scan_workspace(store, profile["id"])
            if profile["goals"] and store.read(profile["id"], "inventory.json"):
                board = generate_personal(store, profile["id"], root, limit=config["collection"]["max_candidates_for_editor"])
                results.append({"name": profile["name"], "status": "ok", "personal": len(board["personal"])})
        except (RuntimeError, ValueError, OSError) as exc:
            results.append({"name": profile["name"], "status": "failed", "detail": str(exc)[:300]})
    return {"sources": statuses, "requests": requests, "public_editor": neutral_status, "public_news": len(public_news["items"]),
            "news_sources": public_news.get("sources", []), "workspaces": results}
