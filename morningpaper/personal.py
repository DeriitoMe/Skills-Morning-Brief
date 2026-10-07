from __future__ import annotations

import json
import tomllib
from datetime import datetime
from pathlib import Path

from .catalog import catalog_public, prepare_catalog
from .core import ROOT, capability_tags, fingerprint, local_zone, now_iso, read_json, write_json
from .hosts import discover_roots
from .leaderboard import balanced_classics, repository_heat
from .providers import ProviderError, generate_json, provider_identity
from .scanner import import_inventory, scan_roots


def scan_workspace(store, workspace_id):
    profile = store.profile(workspace_id)
    if profile.get("inventory_mode") == "imported":
        profile = store.update_workspace(workspace_id, {"inventory_mode": "filesystem"})
    discovered = discover_roots(profile["host"], profile.get("project_directory", ""))
    previous = store.read(workspace_id, "inventory.json", {})
    native = previous.get("native_capabilities", []) if previous.get("host") == profile["host"] else []
    inventory = scan_roots(profile["roots"], profile["host"], discovered.get("config_path"), native)
    inventory.update(workspace_id=workspace_id, instance_id=store.instance_id, scan_version=store.scan_version(profile))
    store.write(workspace_id, "inventory.json", inventory)
    return inventory


def import_workspace_inventory(store, workspace_id, value):
    profile = store.profile(workspace_id)
    inventory = import_inventory(value, profile["host"])
    store.update_workspace(workspace_id, {"inventory_mode": "imported"})
    inventory.update(workspace_id=workspace_id, instance_id=store.instance_id, scan_version=store.scan_version(profile))
    store.write(workspace_id, "inventory.json", inventory)
    return inventory


def personal_context(store, profile, inventory):
    return {"workspace": {key: profile[key] for key in ("name", "host", "goals", "stack", "operating_system")},
            "inventory": {"host": inventory.get("host"), "scan_status": inventory.get("scan_status"),
                          "skills": [{key: row.get(key) for key in ("name", "description", "tags", "scope", "enabled", "availability", "evidence")} for row in inventory["skills"]],
                          "native_capabilities": inventory.get("native_capabilities", []), "errors": inventory.get("errors", [])}}


def validate_matches(result, candidates, inventory):
    by_id = {row["id"]: row for row in candidates}
    existing = {row["name"] for row in inventory["skills"] if row.get("enabled", True)}
    existing.update(row["name"] for row in inventory.get("native_capabilities", []))
    seen = set()
    for analysis in result["analyses"]:
        row = by_id.get(analysis["id"])
        if row is None or analysis["id"] in seen:
            raise ProviderError("个人评价包含未知或重复 Skill")
        if analysis["evidence_paths"] != [row["path"]]:
            raise ProviderError("个人评价引用了尚未读取的证据")
        if any(name not in existing for name in analysis["matched_existing"]):
            raise ProviderError("个人评价引用了清单中不存在的能力")
        if analysis["relation"] in ("covered", "improvement") and not analysis["matched_existing"]:
            raise ProviderError("覆盖关系缺少真实能力对照")
        if analysis["relation"] == "covered" and analysis["category"] != "covered":
            raise ProviderError("覆盖关系与推荐类别不一致")
        seen.add(analysis["id"])
    if seen != set(by_id):
        raise ProviderError("个人评价缺少输入条目")
    return result["analyses"]


def exact_installed(candidate, inventory):
    return next((row for row in inventory["skills"] if row.get("enabled", True) and (
        row.get("catalog_skill_id") == candidate["id"] and row.get("catalog_fingerprint") == candidate["fingerprint"]
        or candidate.get("source_fingerprint") and row.get("source_fingerprint") == candidate["source_fingerprint"])), None)


def generate_personal(store, workspace_id, root=ROOT, limit=18, progress=None, secret=None, candidate_ids=None):
    profile, inventory = store.profile(workspace_id), store.read(workspace_id, "inventory.json")
    if not inventory:
        raise ValueError("请先检查 Skills 或导入自己的能力清单")
    if inventory.get("scan_version") != store.scan_version(profile):
        raise ValueError("Agent 或检查范围已改变，请重新检查 Skills")
    if inventory.get("errors") and not inventory["skills"]:
        raise ValueError("没有成功读取的能力，不能据此判断你缺少哪些技能，请重新检查或导入清单")
    if not profile["goals"]:
        raise ValueError("请先填写当前业务目标，让推荐有明确方向")
    catalog = read_json(root / "data/public/catalog.json") or prepare_catalog(root)
    candidates = catalog["items"]
    if candidate_ids is not None:
        candidates = [row for row in candidates if row["id"] in set(candidate_ids)]
    goals_tags = set(capability_tags(profile["goals"] + " " + profile["stack"]))
    candidates = sorted(candidates, key=lambda row: (not bool(goals_tags & set(row.get("tags", []))), -row.get("stars", 0), row["name"]))
    feedback = store.read(workspace_id, "feedback.json", {})
    instruction = (root / "prompts/personal-fit.md").read_text(encoding="utf-8")
    schema = read_json(root / "prompts/personal-fit.schema.json")
    directory = store.workspace_dir(workspace_id)
    context_version = store.profile_version(profile)
    analyses, pending = {}, []
    for row in candidates:
        key = fingerprint([store.instance_id, workspace_id, row["id"], row["fingerprint"], inventory["version"], context_version,
                           feedback.get(row["id"], {}), instruction])
        cached = read_json(directory / "cache" / (key + ".json"))
        same = exact_installed(row, inventory)
        if same:
            analyses[row["id"]] = {"id": row["id"], "score": 20, "relation": "covered", "category": "covered", "confidence": "medium",
                "summary": row.get("summary", row["description"]), "reason": "当前清单已包含同一 Skill 定义，可先核对现有版本的依赖，避免重复添加。",
                "use_case": "用当前业务的一个小任务验证已有技能是否可调用。", "compatibility_status": "unknown",
                "compatibility_notes": "清单显示已有定义；工具、账号和运行依赖仍需确认。", "matched_existing": [same["name"]], "evidence_paths": [row["path"]], "analysis_method": "exact_inventory_match"}
        elif cached:
            try:
                validated = validate_matches({"analyses": [cached]}, [row], inventory)
                analyses[row["id"]] = validated[0]
            except ProviderError:
                pending.append((row, key))
        else:
            pending.append((row, key))

    def save():
        value = {"schema_version": 1, "workspace_id": workspace_id, "instance_id": store.instance_id, "inventory_version": inventory["version"],
                 "profile_version": context_version, "catalog_version": catalog["version"], "updated_at": now_iso(), "analyses": analyses}
        store.write(workspace_id, "matches.json", value)
        if progress:
            progress(len(analyses), len(candidates))

    save()
    for index in range(0, min(limit, len(pending)), 6):
        batch = pending[index:min(index + 6, limit)]
        rows = [pair[0] for pair in batch]
        from .source_cache import with_source
        rows = [with_source(row, directory / "source-cache") for row in rows]
        payload = {**personal_context(store, profile, inventory), "feedback": {row["id"]: feedback[row["id"]] for row in rows if row["id"] in feedback}, "skills": rows}
        result = generate_json(instruction, payload, schema, profile["provider"], directory / "runtime", secret)
        validated = validate_matches(result, rows, inventory)
        by_id = {row["id"]: row for row in validated}
        for candidate, key in batch:
            analysis = by_id[candidate["id"]]
            if inventory.get("errors") and analysis["relation"] == "new":
                analysis = {**analysis, "score": min(79, analysis["score"]), "confidence": "low",
                            "reason": analysis["reason"] + " 清单还有未成功检查的范围，能力缺口仍需确认。"}
            if analysis["confidence"] == "low":
                analysis["score"] = min(79, analysis["score"])
            analyses[candidate["id"]] = analysis
            write_json(directory / "cache" / (key + ".json"), analysis)
        save()
    publish_private_edition(store, workspace_id, root)
    return board_for_workspace(store, workspace_id, root)


def board_for_workspace(store, workspace_id, root=ROOT):
    catalog = read_json(root / "data/public/catalog.json", {})
    profile = store.profile(workspace_id)
    inventory = store.read(workspace_id, "inventory.json")
    matches = store.read(workspace_id, "matches.json", {})
    needs_scan = not inventory or inventory.get("scan_version") != store.scan_version(profile)
    valid = bool(inventory and not needs_scan and matches.get("inventory_version") == inventory["version"] and matches.get("profile_version") == store.profile_version(profile))
    feedback = store.read(workspace_id, "feedback.json", {})
    items = []
    for source in catalog.get("items", []):
        row = {key: value for key, value in source.items() if key != "source_text"}
        analysis = matches.get("analyses", {}).get(row["id"]) if valid else None
        row["analysis_status"] = "inventory_matched" if analysis and analysis.get("analysis_method") == "exact_inventory_match" else "ai_reviewed" if analysis else "pending"
        if analysis:
            row.update(analysis)
        row["feedback"] = feedback.get(row["id"], {}).get("action", "")
        if row.get("general_score") is not None:
            row["classic_score"] = round(row["general_score"] * .8 + repository_heat(row.get("stars", 0)) * .2)
        items.append(row)
    personal = [row for row in items if row["analysis_status"] == "ai_reviewed" and row.get("score", 0) >= 60
                and row.get("relation") in ("new", "improvement") and row.get("category") in ("gap", "improvement", "exploration")
                and row.get("compatibility_status") in ("documented", "adaptation") and row["feedback"] not in ("not_relevant", "already_have")]
    personal.sort(key=lambda row: (-row["score"], row["feedback"] != "interested", row["name"]))
    classics = balanced_classics([row for row in items if row.get("neutral_status") == "ai_reviewed" and row.get("general_score", 0) >= 60], 4)
    for ranking, label in ((personal, "personal_rank"), (classics, "classic_rank")):
        for index, row in enumerate(ranking, start=1):
            row[label] = index
    repositories = []
    for repo in catalog.get("repositories", []):
        rows = [row for row in items if row["repository"] == repo["name"]]
        repositories.append({**repo, "reviewed_count": sum(row.get("neutral_status") == "ai_reviewed" for row in rows)})
    return {"schema_version": 2, "generated_at": matches.get("updated_at", catalog.get("updated_at", now_iso())), "workspace_id": workspace_id,
            "workspace_name": profile["name"], "host": profile["host"], "items": items, "personal": personal, "classics": classics,
            "repositories": sorted(repositories, key=lambda row: -row.get("stars", 0)), "reviewed_count": sum(row["analysis_status"] in ("ai_reviewed", "inventory_matched") for row in items),
            "pending_review": sum(row["analysis_status"] not in ("ai_reviewed", "inventory_matched") for row in items), "discovered_count": sum(row.get("skill_count", 0) for row in repositories),
            "needs_scan": needs_scan, "needs_goals": not bool(profile["goals"]), "inventory_stale": bool(inventory and not valid),
            "notes": ["通用价值独立于个人画像；个人结果只属于当前工作区。", "文件存在不代表工具和账号已验证可用。",
                      "经典精选分 = 通用价值 80% + 仓库热度 20%；每库先列出四项。", "仓库 Stars 不代表单个 Skill 的独立声誉。"]}


def publish_private_edition(store, workspace_id, root=ROOT):
    board = board_for_workspace(store, workspace_id, root)
    inventory = store.read(workspace_id, "inventory.json", {})
    profile = store.profile(workspace_id)
    history = store.read(workspace_id, "history.json", {})
    rows = [row for row in board["personal"] if row["score"] >= 80 and history.get(row["id"]) != row["fingerprint"]][:3]
    report_id = now_iso().replace(":", "-")
    report = {"schema_version": 2, "id": report_id, "name": "Skills Morning Brief", "workspace_id": workspace_id, "workspace_name": profile["name"],
              "date": datetime.now(local_zone(profile["timezone"])).strftime("%Y年%m月%d日"), "generated_at": now_iso(), "edition_label": "工作区每日变化",
              "lead": "本次发现 " + str(len(rows)) + " 项值得优先试用的能力。" if rows else "本次没有需要重复刊登的新推荐，已核对条目仍保留在长期陈列库。",
              "degraded": bool(inventory.get("errors")), "inventory_stale": False, "inventory_count": len(inventory.get("skills", [])),
              "candidate_count": len(board["items"]), "pending_review": board["pending_review"], "recommendations": rows, "updates": [],
              "observations": [row for row in board["personal"] if row not in rows][:5], "news": [], "sources": [], "notes": board["notes"]}
    for row in rows:
        history[row["id"]] = row["fingerprint"]
    store.write(workspace_id, "history.json", history)
    store.write(workspace_id, "latest.json", report)
    archive = store.read(workspace_id, "archive.json", [])
    entry = {key: report[key] for key in ("id", "date", "generated_at", "edition_label", "lead")}
    store.write(workspace_id, "archive.json", ([entry] + archive)[:90])
    write_json(store.workspace_dir(workspace_id) / "reports" / (report_id + ".json"), report)


def migrate_owner(store, root=ROOT):
    installation = read_json(store.root / "installation.json")
    if installation.get("legacy_migrated"):
        return store.profile(installation["legacy_migrated"])
    settings = read_json(root / "profile/local-roots.json")
    preferences = read_json(root / "profile/preferences.json", {})
    if not settings:
        raise ValueError("此项目没有可迁移的本机资料；请从首次引导开始")
    roots = [{"path": path, "scope": "user", "label": "已确认的本机 Codex 技能目录"} for path in settings.get("user_roots", [])]
    bundle_dirs = sorted({str(Path(path).parent.parent) for path in settings.get("bundled_skill_paths", [])})
    roots += [{"path": path, "scope": "plugin_cache", "label": "本机已发现的插件技能"} for path in bundle_dirs if Path(path).is_dir()]
    if (root / ".agents/skills").is_dir():
        roots.append({"path": str(root / ".agents/skills"), "scope": "project", "label": "当前业务工作区技能"})
    # Bundled SKILL.md paths can point directly at a skill folder; use that folder instead of assuming a layout.
    roots = [{**row, "path": row["path"]} for row in roots]
    profile = store.create_workspace({"name": "迁移的个人方案", "host": "codex", "goals": "；".join(preferences.get("interests", [])),
                                      "roots": roots, "project_directory": str(root), "provider": {"id": "codex"}})
    inventory = scan_workspace(store, profile["id"])
    inventory["native_capabilities"] = preferences.get("native_capabilities", [])
    inventory["version"] = fingerprint([inventory["version"], inventory["native_capabilities"]])
    store.write(profile["id"], "inventory.json", inventory)
    store.write(profile["id"], "feedback.json", read_json(root / "data/feedback.json", {}))
    old_state = read_json(root / "data/state.json", {})
    history = {key: row["fingerprint"] for key, row in old_state.get("history", {}).items() if row.get("section") in ("recommendations", "updates")}
    store.write(profile["id"], "history.json", history)
    installation = read_json(store.root / "installation.json")
    installation["legacy_migrated"] = profile["id"]
    write_json(store.root / "installation.json", installation)
    return profile
