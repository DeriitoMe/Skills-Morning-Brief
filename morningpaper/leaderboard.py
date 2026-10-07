from __future__ import annotations

import math

from .core import ROOT, now_iso, read_json, write_json


def repository_heat(stars):
    """A log scale keeps very large repositories from overwhelming utility."""
    return round(min(100, max(0, math.log10(max(1, stars) / 1000) * 35 + 30)))


def balanced_classics(rows, per_repository=4):
    featured, rest, counts = [], [], {}
    for row in sorted(rows, key=lambda item: (-item["classic_score"], -item.get("general_score", 0), item["name"])):
        repository = row["repository"]
        if counts.get(repository, 0) < per_repository:
            featured.append(row)
            counts[repository] = counts.get(repository, 0) + 1
        else:
            rest.append(row)
    return featured + rest


def build_leaderboard(candidates, state, inventory, config, feedback, previous=None):
    options = config.get("leaderboard", {})
    previous_rows = {row["id"]: row for row in (previous or {}).get("items", [])}
    items = []
    for candidate in candidates:
        row = dict(candidate)
        old = previous_rows.get(row["id"], {})
        row["classic_analysis_status"] = row.get("analysis_status", "pending")
        if row.get("analysis_status") != "ai_reviewed" and old.get("fingerprint") == row["fingerprint"] and old.get("general_score") is not None:
            # A changed personal inventory invalidates personal fit, not the unchanged general assessment.
            for key in ("general_score", "general_reason", "difficulty", "summary", "evidence_paths", "compatibility_status", "compatibility_notes"):
                row.setdefault(key, old.get(key))
            row["classic_analysis_status"] = old.get("classic_analysis_status", "pending")
        row["feedback"] = feedback.get(row["id"], {}).get("action", "")
        row["repository_heat"] = repository_heat(row.get("stars", 0))
        general = row.get("general_score")
        if general is not None:
            row["classic_score"] = round(general * options.get("classic_value_weight", .8) + row["repository_heat"] * options.get("classic_popularity_weight", .2))
        items.append(row)
    official = {row["name"] for row in config.get("repositories", []) if row.get("official")}
    eligible = [row for row in items if row.get("stars", 0) >= config["collection"]["min_stars"] or row["repository"] in official]
    personal = [row for row in eligible if row.get("analysis_status") == "ai_reviewed"
                and row.get("relation") in ("new", "improvement")
                and row.get("score", 0) >= options.get("personal_min_score", 60)
                and row.get("compatibility_status") in ("documented", "adaptation")
                and row.get("evidence_paths")
                and row.get("source_status", "current") in ("current", "source_failed", "stale")
                and row["feedback"] not in ("not_relevant", "already_have")]
    personal.sort(key=lambda row: (-row["score"], row["feedback"] != "interested", -row.get("general_score", 0), row["name"]))
    classics = [row for row in eligible if row.get("classic_analysis_status") == "ai_reviewed"
                and row.get("general_score", 0) >= 60 and row.get("evidence_paths")]
    classics = balanced_classics(classics, options.get("classic_per_repository", 4))
    for ranking, key in ((personal, "personal_rank"), (classics, "classic_rank")):
        for index, row in enumerate(ranking, start=1):
            row[key] = index
    repositories = []
    for name, repo in state.get("repositories", {}).items():
        rows = [row for row in items if row["repository"] == name]
        repositories.append({"name": name, "url": "https://github.com/" + name,
                             "stars": repo.get("stars", max((row.get("stars", 0) for row in rows), default=0)),
                             "skill_count": repo.get("skill_count", len(rows)), "read_count": len(rows),
                             "reviewed_count": sum(row.get("analysis_status") == "ai_reviewed" for row in rows),
                             "checked_at": repo.get("checked_at"), "pending_files": repo.get("pending_files", 0)})
    repositories.sort(key=lambda row: -row["stars"])
    return {"schema_version": 1, "generated_at": now_iso(), "inventory_version": inventory.get("version"),
            "items": items, "personal": personal, "classics": classics, "repositories": repositories,
            "reviewed_count": sum(row.get("analysis_status") == "ai_reviewed" for row in items),
            "pending_review": sum(row.get("analysis_status") != "ai_reviewed" for row in items),
            "discovered_count": sum(row["skill_count"] for row in repositories),
            "notes": ["长期榜覆盖已采集的历史 Skills，不按最近更新时间筛选，也不因已报道而移除。",
                      "适合我的榜按个人增量评分排序，60–79 分为按需了解，80 分起为优先试用。",
                      "经典精选分 = 通用价值 80% + 仓库热度 20%；热度使用对数刻度。每库先列出至多 4 项，再展示其余。",
                      "Stars 属于仓库；经典精选表示来自知名技能库的实用条目，未核实单个 Skill 的独立采用量或口碑。",
                      "目录仍在扩展，数量与采集时间按实际证据披露。"]}


def publish_leaderboard(candidates, state, inventory, config, feedback, root=ROOT):
    board = build_leaderboard(candidates, state, inventory, config, feedback, read_json(root / "web/data/leaderboard.json", {}))
    write_json(root / "web/data/leaderboard.json", board)
    return board
