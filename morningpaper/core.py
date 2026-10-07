from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]


def local_zone(name="Asia/Shanghai"):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name)
        raise


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path, default=None):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temp_path = stream.name
    try:
        os.replace(temp_path, path)
    except OSError as exc:
        if os.name != "nt" or getattr(exc, "winerror", None) != 17:
            raise
        # Some Windows redirected user folders report EXDEV even for sibling paths.
        # Keep the normal atomic path; use Windows' copy-and-replace only for that case.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
        if not kernel.MoveFileExW(str(temp_path), str(path), 1 | 2 | 8):
            raise OSError(ctypes.get_last_error(), "Windows user-data replacement failed") from None


def frontmatter(text):
    """Read bounded display metadata, never evaluate YAML or skill instructions."""
    text = text.lstrip("\ufeff")
    match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
    if not match:
        return {}
    lines = match.group(1).splitlines()
    result = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        field = re.match(r"^([a-z][a-z_-]*):\s*(.*)$", line)
        if field:
            key, value = field.groups()
            if value in ("", "|", ">", "|-", ">-"):
                parts = []
                index += 1
                while index < len(lines) and (
                    not lines[index].strip() or lines[index].startswith((" ", "\t"))
                ):
                    parts.append(lines[index].strip())
                    index += 1
                result[key] = " ".join(parts)
                continue
            result[key] = value.strip().strip("'\"")
        index += 1
    return result


TAG_RULES = {
    "documents": r"(?i)\b(docx|word|documents?)\b|文档",
    "pdf": r"(?i)\bpdf\b",
    "spreadsheets": r"(?i)\b(xlsx|spreadsheets?|excel)\b|表格",
    "presentations": r"(?i)\b(pptx|powerpoint|presentations?)\b|演示文稿",
    "image_generation": r"(?i)\b(imagegen|image generation|generate.*images?)\b|图像生成",
    "video": r"(?i)\b(video|hyperframes|remotion)\b|视频",
    "diagrams": r"(?i)\b(diagrams?|flowchart|architecture visualization)\b|流程图|架构图",
    "frontend_design": r"(?i)\b(frontend|front-end|ux/ui|web design|ui design)\b|前端",
    "browser": r"(?i)\b(browser|playwright|puppeteer)\b|浏览器",
    "web_research": r"(?i)\b(web search|web research|research agent)\b|网页研究",
    "data_collection": r"(?i)\b(scraper|scraping|data collection)\b|数据收集|抓取",
    "skill_authoring": r"(?i)\b(skill-creator|create.*skills?)\b",
    "skill_installation": r"(?i)\b(skill-installer|install.*skills?)\b",
    "security_review": r"(?i)\b(security|vulnerability|threat model|audit|semgrep|codeql)\b|安全审查",
    "testing": r"(?i)\b(testing|test-driven|tdd|unit tests|test coverage)\b",
    "github_ci": r"(?i)\b(github actions|fix ci|ci failures|continuous integration)\b",
    "github_workflow": r"(?i)\b(pull requests?|github workflow|git worktree)\b",
    "memory": r"(?i)\b(agent memory|persistent memory|context management|context engineering)\b|记忆|上下文管理",
    "evals": r"(?i)\b(evals?|evaluations?|benchmarking)\b|评估",
    "rag": r"(?i)\b(rag|retrieval augmented|vector database)\b",
    "observability": r"(?i)\b(observability|tracing|telemetry)\b|可观测",
    "mcp_authoring": r"(?i)\b(mcp builder|mcp server generation|build.*mcp)\b",
    "coding": r"(?i)\b(coding|software development|debugging)\b|代码开发",
}


def capability_tags(text):
    return sorted(key for key, pattern in TAG_RULES.items() if re.search(pattern, text))


def inventory_stale(inventory, max_days=7, at=None):
    if not inventory or not inventory.get("captured_at"):
        return True
    try:
        captured = datetime.fromisoformat(inventory["captured_at"])
        if captured.tzinfo is None:
            return True
        return (at or datetime.now(timezone.utc)) - captured > timedelta(days=max_days)
    except (ValueError, TypeError):
        return True


def inventory_tags(inventory):
    tags = set()
    for skill in inventory.get("skills", []):
        if skill.get("enabled", True) and skill.get("availability") != "unavailable":
            tags.update(skill.get("tags", []))
    for native in inventory.get("native_capabilities", []):
        if native.get("availability") == "available":
            tags.update(native.get("tags", []))
    return tags


def provisional_rank(candidate, inventory, preferences):
    tags = set(candidate.get("tags", []))
    covered = tags & inventory_tags(inventory)
    missing = tags - inventory_tags(inventory)
    has_gap = bool(missing)
    name = candidate["name"].lower()
    exact = [
        item["name"] for item in inventory.get("skills", [])
        if item["name"].lower() == name and item.get("enabled", True)
    ]
    relation = "待核对" if not tags else ("可能补充" if has_gap else "可能已覆盖")
    if exact:
        relation = "已有同名能力"
    score = 35 if has_gap else 5
    score += 20
    score += 5 if candidate.get("compatibility") else 0
    score += 10 if candidate.get("official") else 5
    score += min(10, max(0, candidate.get("stars", 0)) // 1000)
    feedback = candidate.get("feedback", "")
    if feedback in ("not_relevant", "already_have"):
        score -= 25
    return {
        **candidate,
        "provisional_score": max(0, min(79, score)),
        "provisional_relation": relation,
        "covered_tags": sorted(covered),
        "missing_tags": sorted(missing),
        "matched_skills": exact,
        "analysis_status": "pending",
    }


def select_sections(candidates, history, config, stale=False):
    recommendations, updates, observations = [], [], []
    threshold = config["ranking"]["recommendation_threshold"]
    for item in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
        previous = history.get(item["id"])
        same = previous and previous.get("fingerprint") == item["fingerprint"]
        if same and previous.get("section") in ("recommendations", "updates"):
            continue
        verified_editor = item.get("analysis_status") == "ai_reviewed"
        eligible = (
            verified_editor and not stale and item.get("score", 0) >= threshold
            and item.get("relation") in ("new", "improvement")
            and item.get("compatibility_status") in ("documented", "adaptation")
            and item.get("evidence_paths")
            and item.get("source_status", "current") == "current"
            and (item.get("official") or item.get("stars", 0) >= config["collection"]["min_stars"])
            and item.get("feedback") not in ("not_relevant", "already_have")
        )
        if previous and not same and previous.get("section") in ("recommendations", "updates"):
            if eligible and item.get("change_summary") and len(updates) < config["publication"]["max_updates"]:
                updates.append(item)
            continue
        if eligible and len(recommendations) < config["publication"]["max_recommendations"]:
            recommendations.append(item)
        elif not same and len(observations) < 5:
            observations.append(item)
    return recommendations, updates, observations
