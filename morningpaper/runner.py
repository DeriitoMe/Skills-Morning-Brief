from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tomllib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collect import collect
from .core import ROOT, inventory_stale, local_zone, now_iso, read_json, select_sections, write_json
from .editor import review
from .inventory import scan_inventory
from .leaderboard import publish_leaderboard


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() != 87  # invalid PID; access denied is inconclusive
    try:
        exit_code = ctypes.c_ulong()
        return not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value == 259
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def run_lock(root):
    directory = root / "data/locks"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "daily.lock"
    for attempt in range(3):
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "started_at": now_iso()}))
            break
        except FileExistsError:
            try:
                owner = read_json(path, {})
            except ValueError:
                owner = {}
            if not owner.get("pid") or process_alive(owner["pid"]):
                raise RuntimeError("已有晨报任务运行，或锁的所属进程无法确认；请检查 data/locks/daily.lock") from None
            # Keep an audit record of a dead worker; never remove an active worker's lock.
            abandoned = directory / ("abandoned-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".json")
            try:
                path.rename(abandoned)
            except FileNotFoundError:
                pass
    else:
        raise RuntimeError("晨报任务锁竞争，请下次重试")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def public_item(row):
    keys = ("id", "name", "description", "repository", "path", "url", "repository_url", "stars", "stars_delta_7d", "source_fingerprint",
            "collected_at", "first_seen_at", "fingerprint", "official", "tags", "license", "source_status",
            "analysis_status", "reviewed_at", "score", "provisional_score", "provisional_relation", "summary", "reason", "use_case",
            "relation", "general_score", "general_reason", "difficulty", "compatibility_status", "compatibility_notes", "matched_existing", "matched_skills", "evidence_paths", "change_summary", "feedback")
    return {key: row[key] for key in keys if key in row}


def edition_lead(recommendations, updates, pending_review):
    if recommendations:
        return "本期有 " + str(len(recommendations)) + " 项值得试用的能力增量：" + "、".join(row["name"] for row in recommendations) + "。可从已有能力对照和试用场景判断是否适合你。"
    if updates:
        return "本期核对到 " + str(len(updates)) + " 项已报道能力的变化，详情见更新栏。"
    return "本期暂无达到推荐标准的新增能力。" + ("仍有候选待编辑核对。" if pending_review else "可从观察栏查看已有能力的对照结果。")


def markdown(report):
    lines = ["# " + report["name"], "", report["date"] + " · " + report["edition_label"], "", report["lead"], ""]
    for section, title in (("recommendations", "值得试用"), ("updates", "已报道能力的变化"), ("news", "官方动态"), ("observations", "观察与待核对")):
        lines += ["## " + title, ""]
        if not report[section]:
            lines += ["本期没有达到刊登条件的条目。", ""]
        for row in report[section]:
            lines += ["### " + row.get("name", row.get("title", "条目")), "",
                      row.get("summary", row.get("description", "")), ""]
            if section != "news":
                lines += ["- 对你的价值：" + row.get("reason", "尚未完成语义核对"),
                          "- 可以这样试：" + row.get("use_case", "先查看原文与依赖"),
                          "- 兼容性：" + row.get("compatibility_notes", "待核对"),
                          "- 仓库 Stars：" + format(row.get("stars", 0), ",") + "（仓库级）"]
            else:
                lines += ["- 日期：" + row.get("date_label", "待核对"), "- 影响：" + row.get("impact", "")]
            lines += ["- [原始来源](" + row["url"] + ")", ""]
    lines += ["## 本期采集范围", "", "本地能力清单：" + str(report["inventory_count"]) + " 项；待编辑：" + str(report["pending_review"]) + " 项。", ""]
    lines += ["- " + row["source"] + "：" + row["status"] + "；" + row["detail"] for row in report["sources"]]
    return "\n".join(lines) + "\n"


def publish(report, inventory, root):
    directory = root / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / (report["id"] + ".json"), report)
    (directory / (report["id"] + ".md")).write_text(markdown(report), encoding="utf-8")
    write_json(root / "web/data/latest.json", report)
    index = read_json(root / "web/data/archive.json", [])
    entry = {key: report[key] for key in ("id", "date", "generated_at", "edition_label", "lead")}
    index = [entry] + [row for row in index if row["id"] != entry["id"]]
    write_json(root / "web/data/archive.json", index[:90])
    write_json(root / "web/data/inventory.json", inventory)


def daily(root=ROOT, use_ai=True, discovery=True, review_only=False, editor_limit=None):
    config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8-sig"))
    if editor_limit is not None:
        if not 1 <= editor_limit <= 120:
            raise ValueError("编辑数量必须在 1–120 之间")
        config["collection"]["max_candidates_for_editor"] = editor_limit
    with run_lock(root):
        inventory = scan_inventory(root)
        stale = inventory_stale(inventory, config["ranking"]["inventory_max_age_days"]) or bool(inventory["errors"]) or not inventory["skills"]
        preferences = read_json(root / "profile/preferences.json", {})
        feedback = read_json(root / "data/feedback.json", {})
        state = read_json(root / "data/state.json", {"schema_version": 1})
        if review_only:
            candidates, news, statuses, requests = [], [], [], 0
            for repository, repo in state.get("repositories", {}).items():
                captured = repo.get("checked_at", "")
                try:
                    fresh = datetime.now(timezone.utc) - datetime.fromisoformat(captured) <= timedelta(hours=24)
                except (ValueError, TypeError):
                    fresh = False
                candidates += [{**row, "source_status": row.get("source_status", "current") if fresh else "stale"} for row in repo.get("candidates", {}).values()]
                statuses.append({"source": repository, "status": "snapshot" if fresh else "failed", "detail": "复用 " + captured + " 的已采集原文；本轮没有重新检查仓库", "checked_at": captured})
        else:
            candidates, news, statuses, requests = collect(config, inventory, state, root, discovery)
        all_candidates = {}
        failed = {row["source"] for row in statuses if row["status"] == "failed"}
        for repository, repo in state.get("repositories", {}).items():
            for row in repo.get("candidates", {}).values():
                source_status = row.get("source_status", "current")
                all_candidates[row["id"]] = {**row, "source_status": "source_failed" if repository in failed and source_status != "pending_refresh" else source_status}
        all_candidates.update({row["id"]: row for row in candidates})
        history = state.setdefault("history", {})
        pending_news = state.setdefault("pending_news", {})
        for row in news:
            pending_news[row["id"]] = row
        outstanding = []
        for row in list(pending_news.values()):
            previous = history.get("news:" + row["id"])
            if previous and previous.get("fingerprint") == row["fingerprint"]:
                continue
            published = row.get("published_at")
            if published:
                try:
                    if datetime.now(timezone.utc) - datetime.fromisoformat(published.replace("Z", "+00:00")) > timedelta(days=14):
                        continue
                except ValueError:
                    row = {**row, "published_at": None}
            outstanding.append(row)
        # Persist collection checkpoints before expensive editing; failed edits stay retryable.
        write_json(root / "data/state.json", state)
        def publish_progress(rows):
            publish_leaderboard([public_item(row) for row in rows], state, inventory, config, feedback, root)
        ranked, edited_news, lead, editor_status = review(list(all_candidates.values()), outstanding[:6], inventory,
                                                        preferences, feedback, config, root, use_ai, on_progress=publish_progress)
        publish_leaderboard([public_item(row) for row in ranked], state, inventory, config, feedback, root)
        recommendations, updates, observations = select_sections(ranked, history, config, stale)
        news_rows = edited_news[:config["publication"]["max_news"]]
        timestamp = datetime.now(local_zone(config["publication"]["timezone"]))
        report_id = timestamp.strftime("%Y-%m-%d-%H%M%S-%f")
        pending_review = sum(row.get("analysis_status") != "ai_reviewed" for row in ranked)
        degraded = stale or any(row["status"] in ("failed", "disabled") for row in statuses + editor_status)
        lead = edition_lead(recommendations, updates, pending_review)
        report = {
            "schema_version": 1, "id": report_id, "name": config["publication"]["name"],
            "date": timestamp.strftime("%Y年%m月%d日"), "generated_at": now_iso(),
            "edition_label": "试刊 · 首次建立基线" if not history else "每日版",
            "lead": lead, "degraded": degraded, "inventory_stale": stale,
            "inventory_count": len(inventory["skills"]), "candidate_count": len(ranked),
            "pending_review": pending_review, "github_requests": requests,
            "recommendations": [public_item(row) for row in recommendations],
            "updates": [public_item(row) for row in updates],
            "observations": [public_item(row) for row in observations],
            "news": [{key: value for key, value in row.items() if key != "source_text"} for row in news_rows],
            "sources": statuses + editor_status,
            "notes": ["Stars 为采集时的仓库级数据；未满 7 天积累时不估算增长。", "采集采用预算与轮换，覆盖范围列在本期来源中。", "推荐依据文档核对，试用前仍需确认账户、依赖和许可。"],
        }
        publish(report, inventory, root)
        for section in ("recommendations", "updates", "observations"):
            for row in report[section]:
                history[row["id"]] = {"fingerprint": row["fingerprint"], "section": section, "reported_at": report["generated_at"]}
        for row in news_rows:
            history["news:" + row["id"]] = {"fingerprint": row["fingerprint"], "section": "news", "reported_at": report["generated_at"]}
            pending_news.pop(row["id"], None)
        state["last_report_id"] = report_id
        state["pending_news"] = dict(list(pending_news.items())[-50:])
        write_json(root / "data/state.json", state)
        write_json(root / "data/runs" / (report_id + ".json"), {"generated_at": report["generated_at"], "degraded": degraded,
                   "sources": report["sources"], "recommendations": len(recommendations), "pending_review": pending_review})
        return report


def main():
    parser = argparse.ArgumentParser(description="Skills Morning Brief")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    sub.add_parser("migrate-owner")
    sub.add_parser("reader-start")
    sub.add_parser("open")
    sub.add_parser("refresh")
    sub.add_parser("monitor")
    neutral = sub.add_parser("catalog")
    neutral.add_argument("--provider", choices=["codex", "deepseek"], default="codex")
    neutral.add_argument("--limit", type=int, default=80)
    personal = sub.add_parser("recommend")
    personal.add_argument("workspace_id")
    personal.add_argument("--limit", type=int, default=18)
    snapshot = sub.add_parser("import-snapshot")
    snapshot.add_argument("path")
    run = sub.add_parser("run")
    run.add_argument("--no-ai", action="store_true", help="只采集，不把启发式结果视为 AI 推荐")
    run.add_argument("--no-discovery", action="store_true", help="本轮只读种子仓库")
    run.add_argument("--review-only", action="store_true", help="只编辑已有采集快照；超过 24 小时的快照不进入推荐")
    run.add_argument("--editor-limit", type=int, help="一次性扩展基线的编辑数量，1–120；不修改每日预算")
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "inventory":
            inventory = scan_inventory()
            print(json.dumps({"skills": len(inventory["skills"]), "errors": inventory["errors"]}, ensure_ascii=False))
        elif args.command == "run":
            report = daily(use_ai=not args.no_ai, discovery=not args.no_discovery, review_only=args.review_only, editor_limit=args.editor_limit)
            print(json.dumps({"report": report["id"], "recommendations": len(report["recommendations"]), "pending_review": report["pending_review"], "degraded": report["degraded"]}, ensure_ascii=False))
        elif args.command == "import-snapshot":
            from .snapshots import import_snapshots
            with run_lock(ROOT):
                results = import_snapshots(args.path)
            print(json.dumps(results, ensure_ascii=False))
        elif args.command == "migrate-owner":
            from .personal import migrate_owner
            from .private_store import PrivateStore
            profile = migrate_owner(PrivateStore())
            print(json.dumps({"workspace_id": profile["id"], "name": profile["name"]}, ensure_ascii=False))
        elif args.command in ("reader-start", "open"):
            from .launcher import start_reader
            print(start_reader(open_browser=args.command == "open"))
        elif args.command == "catalog":
            from .catalog import prepare_catalog, evaluate_catalog
            with run_lock(ROOT):
                catalog = prepare_catalog()
                evaluate_catalog(catalog, {"id": args.provider}, ROOT / ".runtime/catalog", limit=args.limit,
                                 progress=lambda done, total: print(str(done) + "/" + str(total), flush=True))
        elif args.command == "recommend":
            from .private_store import PrivateStore
            from .personal import generate_personal
            board = generate_personal(PrivateStore(), args.workspace_id, limit=args.limit,
                                      progress=lambda done, total: print(str(done) + "/" + str(total), flush=True))
            print(json.dumps({"personal": len(board["personal"]), "reviewed": board["reviewed_count"]}, ensure_ascii=False))
        elif args.command in ("refresh", "monitor"):
            from .shelf_daily import refresh_all
            print(json.dumps(refresh_all(personal=args.command == "refresh"), ensure_ascii=False))
        else:
            from .shelf_server import serve_shelf
            serve_shelf(port=args.port)
    except (OSError, ValueError, RuntimeError) as exc:
        print("晨报任务未完成：" + str(exc), file=sys.stderr)
        return 1
    return 0
