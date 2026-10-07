import copy
import tomllib
import unittest
from pathlib import Path

from morningpaper.collect import is_skill_path
from morningpaper.leaderboard import balanced_classics, build_leaderboard

CONFIG=tomllib.loads((Path(__file__).resolve().parents[1]/"config.toml").read_text(encoding="utf-8"))
ROW={"id":"1:skills/debug/SKILL.md","name":"debug","repository":"owner/repo","path":"skills/debug/SKILL.md",
     "fingerprint":"same","stars":5000,"analysis_status":"ai_reviewed","source_status":"current","score":85,
     "general_score":92,"general_reason":"定位根因","difficulty":"beginner","relation":"improvement",
     "compatibility_status":"documented","evidence_paths":["skills/debug/SKILL.md"],"summary":"系统调试"}


class LeaderboardTests(unittest.TestCase):
    def build(self,rows=None,feedback=None,previous=None):
        rows=rows if rows is not None else [copy.deepcopy(ROW)]
        state={"repositories":{"owner/repo":{"skill_count":25,"stars":5000}},
               "history":{ROW["id"]:{"fingerprint":"same","section":"recommendations"}}}
        return build_leaderboard(rows,state,{"version":"inventory"},CONFIG,feedback or {},previous)

    def test_reported_unchanged_skill_stays_on_long_term_board(self):
        board=self.build()
        self.assertEqual(board["personal"][0]["id"],ROW["id"])
        self.assertEqual(board["classics"][0]["id"],ROW["id"])

    def test_covered_classic_remains_visible_without_personal_recommendation(self):
        board=self.build([{**ROW,"relation":"covered","score":30}])
        self.assertFalse(board["personal"])
        self.assertEqual(board["classics"][0]["name"],"debug")

    def test_explicit_feedback_changes_personal_board_and_preserves_classic(self):
        board=self.build(feedback={ROW["id"]:{"action":"already_have"}})
        self.assertFalse(board["personal"])
        self.assertTrue(board["classics"])

    def test_unknown_compatibility_never_becomes_personal_recommendation(self):
        board=self.build([{**ROW,"compatibility_status":"unknown"}])
        self.assertFalse(board["personal"])
        self.assertTrue(board["classics"])

    def test_temporary_source_failure_retains_reviewed_historical_knowledge(self):
        board=self.build([{**ROW,"source_status":"source_failed"}])
        self.assertEqual(board["personal"][0]["source_status"],"source_failed")
        self.assertTrue(board["classics"])

    def test_known_changed_unread_source_is_not_a_personal_recommendation(self):
        board=self.build([{**ROW,"source_status":"pending_refresh"}])
        self.assertFalse(board["personal"])

    def test_old_general_value_survives_personal_inventory_refresh(self):
        previous=self.build()
        pending={key:value for key,value in ROW.items() if key not in ("general_score","general_reason","difficulty","evidence_paths","compatibility_status")}
        pending["analysis_status"]="pending"
        board=self.build([pending],previous=previous)
        self.assertFalse(board["personal"])
        self.assertEqual(board["classics"][0]["general_score"],92)
        self.assertEqual(board["pending_review"],1)

    def test_source_change_cannot_reuse_old_general_assessment(self):
        previous=self.build()
        pending={"id":ROW["id"],"name":"debug","repository":"owner/repo","fingerprint":"changed","stars":5000,"analysis_status":"pending"}
        self.assertFalse(self.build([pending],previous=previous)["classics"])

    def test_classic_home_does_not_only_show_one_large_repository(self):
        rows=[{**ROW,"name":"a"+str(i),"classic_score":100-i} for i in range(6)]
        rows.append({**ROW,"name":"other","repository":"another/repo","classic_score":70})
        ranked=balanced_classics(rows,4)
        self.assertEqual(ranked[4]["name"],"other")
        self.assertEqual(len(ranked),7)

    def test_repository_stars_are_not_individual_skill_stars(self):
        board=self.build()
        self.assertEqual(board["repositories"][0]["skill_count"],25)
        self.assertEqual(board["repositories"][0]["read_count"],1)
        self.assertEqual(board["discovered_count"],25)
        self.assertNotIn("individual_stars",board["items"][0])

    def test_test_fixtures_are_not_skills_for_recommendation(self):
        self.assertTrue(is_skill_path("skills/systematic-debugging/SKILL.md"))
        self.assertFalse(is_skill_path("plugins/fixtures/skills/mock/SKILL.md"))
        self.assertFalse(is_skill_path("template/SKILL.md"))


if __name__=="__main__":
    unittest.main()
