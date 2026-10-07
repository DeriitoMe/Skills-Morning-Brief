import tempfile
import unittest
from pathlib import Path

from morningpaper.core import read_json, write_json
from morningpaper.snapshots import import_snapshots


class SnapshotTests(unittest.TestCase):
    def payload(self, skills=None):
        return {"provider":"GitHub plugin","snapshots":[{"repository":"owner/repo",
            "metadata":{"full_name":"owner/repo","id":1,"stargazers_count":5000,"html_url":"https://github.com/owner/repo"},
            "commit_sha":"a"*40,"captured_at":"2026-10-06 05:00:00 UTC",
            "tree":{"sha":"tree","truncated":False,"tree":[{"path":"skills/debug/SKILL.md","sha":"changed","type":"blob","mode":"100644"}]},
            "skills":skills or []}]}

    def test_changed_unread_skill_remains_pending_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write_json(root/"data/state.json",{"repositories":{"owner/repo":{"candidates":{"skills/debug/SKILL.md":{"id":"old","fingerprint":"before","source_status":"current"}}}}})
            path=root/"snapshot.json";write_json(path,self.payload())
            import_snapshots(path,root)
            row=read_json(root/"data/state.json")["repositories"]["owner/repo"]["candidates"]["skills/debug/SKILL.md"]
            self.assertEqual(row["source_status"],"pending_refresh")
            self.assertEqual(row["fingerprint"],"before")

    def test_real_skill_text_and_commit_are_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/"snapshot.json"
            write_json(path,self.payload([{"path":"skills/debug/SKILL.md","text":"---\nname: debug\ndescription: Find a root cause.\n---\nRead the code."}]))
            results=import_snapshots(path,root)
            self.assertEqual(results[0]["imported"],1)
            row=read_json(root/"data/state.json")["repositories"]["owner/repo"]["candidates"]["skills/debug/SKILL.md"]
            self.assertIn("/blob/"+"a"*40+"/",row["url"])
            self.assertEqual(row["source_provider"],"GitHub plugin")
            self.assertEqual(row["source_status"],"current")


if __name__=="__main__":
    unittest.main()
