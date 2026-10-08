import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from morningpaper.core import read_json, write_json
from morningpaper.tibo_watch import SourceError, classify_post, is_reset_topic, mark_conflicts, merge_records, refresh_tibo, tibo_public, verify_oembed


POST_ID = "2107913674593644711"
POST_URL = "https://x.com/thsottiaux/status/" + POST_ID


def post(text, identity=POST_ID):
    return {"id": identity, "url": "https://x.com/thsottiaux/status/" + identity,
            "text": text, "published_at": "2026-10-07", "date_precision": "day", "truncated": False}


def embed(text, author="thsottiaux", identity=POST_ID):
    return json.dumps({"author_url": "https://x.com/" + author, "url": "https://x.com/" + author + "/status/" + identity,
                       "html": '<blockquote><p>' + text + '</p><a href="https://x.com/' + author + '/status/' + identity + '">October 7, 2026</a></blockquote>'})


class TiboTests(unittest.TestCase):
    def test_only_usage_resets_enter_the_column(self):
        self.assertFalse(is_reset_topic("GPT-6 has shipped"))
        self.assertFalse(is_reset_topic("Reset your ChatGPT password"))
        self.assertTrue(is_reset_topic("Codex usage limits reset tomorrow"))

    def test_signoff_tomorrow_is_never_a_reset_time(self):
        row = classify_post(post("Codex update. Loading a banked reset in everyone's paid accounts. See you again tomorrow!"))
        self.assertEqual(row["event_status"], "in_progress")
        self.assertEqual(row["reset_time_text"], "原文未给出确切重置时刻")
        self.assertIsNone(row["reset_at"])
        self.assertNotIn("Plus", row["scope"])

    def test_relative_reset_time_is_preserved_without_timezone_guess(self):
        row = classify_post(post("We will reset Codex limits tomorrow at 10am PST."))
        self.assertIsNone(row["reset_at"])
        self.assertIn("10am PST", row["reset_time_text"])
        self.assertEqual(row["event_status"], "announced")

    def test_banked_question_is_not_mistaken_for_a_new_grant(self):
        row = classify_post(post("How many banked resets do you have in Codex?"))
        self.assertNotIn("补发", row["title"])
        self.assertIn("没有据此确认为账户新补发", row["summary"])

    def test_processed_word_does_not_imply_pro_plan_scope(self):
        row = classify_post(post("The Codex reset has been processed."))
        self.assertNotIn("Pro", row["scope"])

    def test_publisher_must_confirm_author_and_link(self):
        with self.assertRaises(SourceError):
            verify_oembed(POST_ID, lambda *_a, **_k: embed("Codex reset", author="someone-else"))
        verified = verify_oembed(POST_ID, lambda *_a, **_k: embed("Codex limits reset"))
        self.assertEqual(verified["published_at"], "2026-10-07")
        self.assertEqual(verified["date_precision"], "day")

    def test_same_post_and_same_day_duplicate_do_not_republish(self):
        row = classify_post(post("We reset all Codex usage limits."))
        rows, new, _ = merge_records([], [row]); self.assertEqual(new, 1)
        again = copy.deepcopy(row); again["id"] = "x:2107913674593644799"; again["url"] += "?duplicate"
        rows, new, updated = merge_records(rows, [row, again])
        self.assertEqual((len(rows), new, updated), (1, 0, 0))

    def test_conflicting_verified_thread_times_are_explicitly_flagged(self):
        first = classify_post(post("We will reset Codex limits tomorrow at 10am PST."))
        second = copy.deepcopy(first); second["id"] += "b"; second["reset_time_text"] = "tomorrow at 12pm PST"
        first["conflict_group"] = second["conflict_group"] = "verified-thread"
        self.assertTrue(all(row["verification"] == "conflicting" for row in mark_conflicts([first, second])))

    def test_public_export_excludes_raw_text_credentials_and_private_fields(self):
        data = {"session_api_key": "private-marker", "items": [{"id": "p", "title": "public", "text": "private-marker", "goals": "private-marker"}],
                "sources": [{"source": "X", "Authorization": "private-marker"}]}
        self.assertNotIn("private-marker", json.dumps(tibo_public(data)))

    def test_full_failure_preserves_old_messages_and_marks_unavailable(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True):
            root = Path(folder); old = classify_post(post("We reset all Codex limits."))
            write_json(root / "data/public/tibo.json", {"items": [old], "references": [], "last_success_at": "2026-10-07T01:00:00Z"})
            def fail(*args, **kwargs): raise SourceError("unavailable")
            result = refresh_tibo(root, getter=fail)
            self.assertEqual(result["items"][0]["id"], old["id"])
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["last_success_at"], "2026-10-07T01:00:00Z")

    def test_mirror_body_is_never_a_publication_fact(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True):
            root = Path(folder)
            def fake(url, **kwargs):
                if "noodl3" in url or "twiscan" in url: return POST_URL + " Codex reset exactly 8am private-marker"
                raise SourceError("publisher blocked")
            result = refresh_tibo(root, getter=fake)
            self.assertEqual(result["items"], [])
            self.assertNotIn("private-marker", json.dumps(result))

    def test_private_x_account_is_rejected_before_reading_tweets(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"X_BEARER_TOKEN": "test-key"}, clear=True):
            def fake(url, **kwargs):
                calls.append(url)
                if "users/by/username" in url: return json.dumps({"data": {"id": "123", "username": "thsottiaux", "protected": True}})
                raise SourceError("unavailable")
            result = refresh_tibo(Path(folder), getter=fake)
            self.assertFalse(any("/tweets?" in url for url in calls))
            self.assertNotIn("test-key", json.dumps(result))

    def test_verified_cache_rotates_to_previously_unread_posts(self):
        identities = [str(int(POST_ID) + i) for i in range(3)]
        calls = []
        def fake(url, **kwargs):
            if "noodl3" in url or "twiscan" in url: return " ".join("https://x.com/thsottiaux/status/" + value for value in identities)
            if "oembed" in url:
                import urllib.parse
                value = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["url"][0].split("/")[-1]
                calls.append(value); return embed("An unrelated coding update.", identity=value)
            raise SourceError("unavailable")
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True):
            root = Path(folder)
            refresh_tibo(root, getter=fake, max_verifications=1)
            refresh_tibo(root, getter=fake, max_verifications=1)
            self.assertEqual(len(set(calls)), 2)


if __name__ == "__main__": unittest.main()
