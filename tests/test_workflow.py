import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from morningpaper.collect import CollectionError, collect_repository
from morningpaper.core import inventory_stale, select_sections
from morningpaper.editor import EditorError, validate_result
from morningpaper.runner import daily, edition_lead, run_lock

BASE = Path(__file__).resolve().parents[1]
CONFIG = {"collection": {"min_stars": 1000, "observation_stars": 500, "max_new_files_per_repository": 1},
          "ranking": {"recommendation_threshold": 80, "inventory_max_age_days": 7},
          "publication": {"max_recommendations": 3, "max_updates": 3}}
ITEM = {"id": "1:skills/eval/SKILL.md", "name": "eval", "path": "skills/eval/SKILL.md", "fingerprint": "abc",
        "repository": "owner/repo", "url": "https://github.com/owner/repo/blob/a/skills/eval/SKILL.md", "stars": 2000,
        "source_status": "current", "analysis_status": "ai_reviewed", "score": 90, "relation": "new",
        "compatibility_status": "documented", "evidence_paths": ["skills/eval/SKILL.md"]}


class WorkflowTests(unittest.TestCase):
    def test_dead_worker_lock_is_recovered_but_live_worker_is_respected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / "data/locks/daily.lock"
            lock.parent.mkdir(parents=True)
            lock.write_text('{"pid": 12345}', encoding="utf-8")
            with patch("morningpaper.runner.process_alive", return_value=True), self.assertRaises(RuntimeError):
                with run_lock(root):
                    pass
            with patch("morningpaper.runner.process_alive", return_value=False):
                with run_lock(root):
                    self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())
            self.assertEqual(len(list(lock.parent.glob("abandoned-*.json"))), 1)

    def test_lead_describes_published_recommendations(self):
        lead = edition_lead([ITEM], [], 4)
        self.assertIn(ITEM["name"], lead)
        self.assertIn("1 项", lead)

    def test_observation_can_be_promoted_without_source_change(self):
        history = {ITEM["id"]: {"fingerprint": "abc", "section": "observations"}}
        self.assertEqual(select_sections([ITEM], history, CONFIG)[0], [ITEM])

    def test_published_recommendation_does_not_repeat(self):
        history = {ITEM["id"]: {"fingerprint": "abc", "section": "recommendations"}}
        self.assertEqual(select_sections([ITEM], history, CONFIG), ([], [], []))

    def test_uncertain_or_stale_or_failed_source_never_recommended(self):
        for changes in ({"analysis_status": "pending"}, {"compatibility_status": "unknown"},
                        {"source_status": "source_failed"}, {"stars": 700}, {"feedback": "already_have"}):
            with self.subTest(changes=changes):
                self.assertFalse(select_sections([{**ITEM, **changes}], {}, CONFIG)[0])
        self.assertFalse(select_sections([ITEM], {}, CONFIG, stale=True)[0])

    def test_changed_item_requires_explained_change_for_update(self):
        history = {ITEM["id"]: {"fingerprint": "old", "section": "recommendations"}}
        self.assertFalse(select_sections([ITEM], history, CONFIG)[1])
        row = {**ITEM, "change_summary": "新增测试流程"}
        self.assertEqual(select_sections([row], history, CONFIG)[1], [row])

    def test_inventory_expiry(self):
        at = datetime.now(timezone.utc)
        self.assertTrue(inventory_stale({"captured_at": (at - timedelta(days=8)).isoformat()}, at=at))
        self.assertFalse(inventory_stale({"captured_at": at.isoformat()}, at=at))

    def test_editor_rejects_unread_evidence_and_invented_local_skills(self):
        analysis = {"id": ITEM["id"], "score": 90, "general_score": 90, "general_reason": "可重复评估", "difficulty": "intermediate", "relation": "new", "summary": "评估", "reason": "有用", "use_case": "比较输出",
                    "compatibility_status": "documented", "compatibility_notes": "仅文档核对", "matched_existing": [],
                    "evidence_paths": [ITEM["path"]], "change_summary": ""}
        result = {"lead": "评估", "analyses": [analysis], "news": []}
        self.assertTrue(validate_result(result, [ITEM], [], {"skills": []}))
        for changes in ({"evidence_paths": ["scripts/not-read.py"]}, {"matched_existing": ["fictional"]},
                        {"id": "wrong"}, {"change_summary": "今天发布"}):
            with self.subTest(changes=changes), self.assertRaises(EditorError):
                validate_result({**result, "analyses": [{**analysis, **changes}]}, [ITEM], [], {"skills": []})

    def test_pinned_source_uses_commit_sha_and_failed_file_stays_pending(self):
        class FakeClient:
            def api(self, path, params=None):
                if path == "/repos/owner/repo":
                    return {"id": 1, "default_branch": "main", "stargazers_count": 2000, "html_url": "https://github.com/owner/repo"}
                if "/branches/" in path:
                    return {"commit": {"sha": "COMMIT"}}
                if "/git/trees/" in path:
                    return {"sha": "TREE", "tree": [{"path": ITEM["path"], "type": "blob", "mode": "100644", "sha": "BLOB"}]}
                raise CollectionError("offline")
        old = {**ITEM, "fingerprint": "old"}
        state = {"repositories": {"owner/repo": {"candidates": {ITEM["path"]: old}, "last_complete_at": "before"}}}
        rows, status = collect_repository(FakeClient(), {"name": "owner/repo"}, state, {"skills": []}, CONFIG)
        self.assertEqual(status["status"], "partial")
        self.assertEqual(state["repositories"]["owner/repo"]["last_complete_at"], "before")
        # A failed changed file must not be treated as current.
        self.assertEqual(rows[0]["source_status"], "pending_refresh")

    def test_news_is_retryable_after_editor_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "profile").mkdir()
            (root / "config.toml").write_text((BASE / "config.toml").read_text(encoding="utf-8"), encoding="utf-8")
            news = {"id": "n1", "fingerprint": "hash", "url": "https://learn.chatgpt.com/docs/whats-new"}
            inventory = {"captured_at": datetime.now(timezone.utc).isoformat(), "skills": [{"name": "local"}], "errors": []}
            with patch("morningpaper.runner.scan_inventory", return_value=inventory), patch("morningpaper.runner.collect", return_value=([], [news], [], 1)), patch("morningpaper.runner.review", return_value=([], [], "", [])):
                daily(root)
            saved = json.loads((root / "data/state.json").read_text(encoding="utf-8"))
            self.assertIn("n1", saved["pending_news"])


if __name__ == "__main__":
    unittest.main()
