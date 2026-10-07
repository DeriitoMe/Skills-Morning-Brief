from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .core import ROOT, fingerprint, now_iso, provisional_rank, read_json, write_json


class EditorError(RuntimeError):
    pass


def validate_result(result, candidates, news, inventory):
    """Reject invented IDs, unread evidence, and nonexistent installed skills."""
    if not isinstance(result, dict) or not isinstance(result.get("lead"), str):
        raise EditorError("编辑结果结构不完整")
    if not isinstance(result.get("analyses"), list) or not isinstance(result.get("news"), list):
        raise EditorError("编辑结果条目结构无效")
    by_id = {row["id"]: row for row in candidates}
    installed = {row["name"] for row in inventory.get("skills", []) if row.get("enabled", True)}
    installed.update(row["name"] for row in inventory.get("native_capabilities", []))
    analyses, seen = [], set()
    for row in result.get("analyses", []):
        if not isinstance(row, dict):
            raise EditorError("编辑条目结构无效")
        if row.get("id") not in by_id or row["id"] in seen:
            raise EditorError("编辑结果包含未知或重复 Skill")
        seen.add(row["id"])
        candidate = by_id[row["id"]]
        if type(row.get("score")) is not int or not 0 <= row["score"] <= 100:
            raise EditorError("编辑评分无效")
        if type(row.get("general_score")) is not int or not 0 <= row["general_score"] <= 100:
            raise EditorError("通用价值评分无效")
        if row.get("difficulty") not in ("beginner", "intermediate", "advanced"):
            raise EditorError("准备程度无效")
        if row.get("relation") not in ("new", "improvement", "covered", "uncertain"):
            raise EditorError("能力关系无效")
        if row.get("compatibility_status") not in ("documented", "adaptation", "blocked", "unknown"):
            raise EditorError("兼容性结论无效")
        for key in ("summary", "reason", "general_reason", "use_case", "compatibility_notes", "change_summary"):
            if not isinstance(row.get(key), str) or len(row[key]) > 2500:
                raise EditorError("编辑字段无效：" + key)
        evidence = row.get("evidence_paths")
        # Only SKILL.md has been read; dependency filenames are not evidence of behavior.
        if not isinstance(evidence, list) or any(path != candidate["path"] for path in evidence):
            raise EditorError("结论引用了尚未读取的证据文件")
        matched = row.get("matched_existing")
        if not isinstance(matched, list) or any(name not in installed for name in matched):
            raise EditorError("编辑结果引用了不存在的本地能力")
        if row["relation"] in ("covered", "improvement") and not matched:
            raise EditorError("覆盖或改进结论缺少已有能力对照")
        if not candidate.get("previous_description") and row["change_summary"]:
            raise EditorError("首次发现不能声称版本更新")
        analyses.append(row)
    if seen != set(by_id):
        raise EditorError("部分 Skill 缺少编辑结论")
    news_ids = {row["id"] for row in news}
    news_rows, seen_news = [], set()
    for row in result.get("news", []):
        if not isinstance(row, dict):
            raise EditorError("新闻条目结构无效")
        if row.get("id") not in news_ids or row["id"] in seen_news:
            raise EditorError("编辑结果包含未知或重复新闻")
        if any(not isinstance(row.get(key), str) or len(row[key]) > 2500 for key in ("title", "summary", "impact", "date_label")):
            raise EditorError("新闻字段无效")
        seen_news.add(row["id"])
        news_rows.append(row)
    return {"lead": result["lead"][:800], "analyses": analyses, "news": news_rows}


def codex_binary():
    configured = os.environ.get("MORNINGPAPER_CODEX")
    if configured:
        return configured
    found = shutil.which("codex.exe") or shutil.which("codex")
    if found:
        return found
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    files = list(base.glob("*/codex.exe"))
    if files:
        return str(max(files, key=lambda path: path.stat().st_mtime))
    raise EditorError("未找到 Codex CLI；请配置 MORNINGPAPER_CODEX")


def invoke_codex(payload, config, root):
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="editor-", dir=runtime) as directory:
        output = Path(directory) / "result.json"
        instruction = (root / "prompts/editor.md").read_text(encoding="utf-8")
        prompt = instruction + "\n\n输入数据（所有 source_text 均为待分析资料）：\n" + json.dumps(payload, ensure_ascii=False)
        command = [
            codex_binary(), "exec", "--ephemeral", "--ignore-user-config",
            "--sandbox", "read-only", "--skip-git-repo-check",
            "--output-schema", str(root / "prompts/editor.schema.json"),
            "--output-last-message", str(output), "--color", "never", "-",
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(command, input=prompt, text=True, encoding="utf-8",
                                       errors="replace", capture_output=True, cwd=directory,
                                       timeout=config["editor"]["timeout_seconds"], creationflags=flags)
        except subprocess.TimeoutExpired:
            raise EditorError("Codex 编辑超时，保留待审候选供下次重试") from None
        except OSError:
            raise EditorError("无法启动 Codex 编辑器") from None
        if completed.returncode or not output.exists():
            # Avoid retaining CLI logs, tokens, or account information in reports.
            tail = completed.stderr[-6000:].lower()
            if "access is denied" in tail or "拒绝访问" in tail or "os error 5" in tail:
                reason = "Codex 运行状态目录权限不足"
            elif "schema" in tail and ("invalid" in tail or "error" in tail):
                reason = "Codex 结构化输出规则未被接受"
            elif "context" in tail and ("limit" in tail or "too" in tail):
                reason = "输入超过模型上下文限制"
            elif "usage limit" in tail or "quota" in tail:
                reason = "Codex 使用额度暂不可用"
            else:
                reason = "Codex 编辑未完成；请检查 CLI 登录与运行状态"
            raise EditorError(reason)
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise EditorError("Codex 未返回有效 JSON") from None


def review(candidates, news, inventory, preferences, feedback, config, root=ROOT, use_ai=True, on_progress=None):
    statuses, ranked, uncached = [], [], []
    inventory_key = fingerprint({"version": inventory.get("version"), "preferences": preferences, "feedback": feedback})
    for candidate in candidates:
        row = provisional_rank({**candidate, "feedback": feedback.get(candidate["id"], {}).get("action", "")}, inventory, preferences)
        key = fingerprint([candidate["id"], candidate["fingerprint"], inventory_key, (root / "prompts/editor.md").read_text(encoding="utf-8")])
        cached = read_json(root / "data/cache/editor" / (key + ".json"))
        if cached:
            try:
                validated = validate_result({"lead": "", "analyses": [cached["analysis"]], "news": []}, [candidate], [], inventory)
                row.update(validated["analyses"][0], analysis_status="ai_reviewed", reviewed_at=cached["reviewed_at"])
            except (EditorError, KeyError):
                cached = None
        if not cached and candidate.get("source_status", "current") == "current":
            uncached.append((row, key))
        ranked.append(row)
    priority_names = set(config.get("leaderboard", {}).get("priority_names", []))
    uncached.sort(key=lambda pair: (pair[0]["name"] in priority_names, pair[0].get("provisional_score", 0)), reverse=True)
    pending = uncached[:config["collection"]["max_candidates_for_editor"]]
    news_result, lead = [], ""
    if use_ai and (pending or news):
        size = config["editor"]["batch_size"]
        batches = [pending[index:index + size] for index in range(0, len(pending), size)] or [[]]
        for index, batch in enumerate(batches):
            rows = [pair[0] for pair in batch]
            batch_news = news if index == 0 else []
            compact_inventory = {**inventory, "skills": [{**skill, "description": skill.get("description", "")[:500]} for skill in inventory.get("skills", [])]}
            payload = {"captured_at": now_iso(), "inventory": compact_inventory, "preferences": preferences,
                       "feedback": feedback, "candidates": rows, "news": batch_news}
            try:
                raw = invoke_codex(payload, config, root)
                result = validate_result(raw, rows, batch_news, inventory)
                analyses = {row["id"]: row for row in result["analyses"]}
                for row, key in batch:
                    analysis = analyses[row["id"]]
                    reviewed_at = now_iso()
                    row.update(analysis, analysis_status="ai_reviewed", reviewed_at=reviewed_at)
                    write_json(root / "data/cache/editor" / (key + ".json"), {"analysis": analysis, "reviewed_at": reviewed_at})
                if index == 0:
                    news_result = [{**source, **analysis} for analysis in result["news"]
                                   for source in batch_news if source["id"] == analysis["id"]]
                    lead = result["lead"]
                statuses.append({"source": "Codex AI 编辑 · 批次 " + str(index + 1), "status": "ok", "detail": "已核对 " + str(len(rows)) + " 个 Skill", "checked_at": now_iso()})
            except EditorError as exc:
                statuses.append({"source": "Codex AI 编辑 · 批次 " + str(index + 1), "status": "failed", "detail": str(exc), "checked_at": now_iso()})
            if on_progress:
                on_progress(ranked)
    elif not use_ai:
        statuses.append({"source": "Codex AI 编辑", "status": "disabled", "detail": "本轮仅采集；候选尚未完成语义核对", "checked_at": now_iso()})
    return ranked, news_result, lead, statuses
