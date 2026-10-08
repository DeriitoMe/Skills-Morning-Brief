"""Public announcement regressions; fixtures never access accounts or the network."""
import copy
import json
import shutil
import subprocess
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import morningpaper.tibo_watch as watch


POST_ID = "2107913674593644711"
ROOT = Path(__file__).resolve().parents[1]


def post(text, identity=POST_ID, verified_at="2026-10-07T01:00:00Z"):
    return {"id": identity, "url": "https://x.com/thsottiaux/status/" + identity,
            "text": text, "published_at": "2026-10-07", "date_precision": "day",
            "truncated": False, "verified_at": verified_at}


def embed(text, identity=POST_ID, date="October 7, 2026", extra_html=""):
    canonical = "https://x.com/thsottiaux/status/" + identity
    return json.dumps({"author_url": "https://x.com/thsottiaux", "url": canonical,
                       "html": '<blockquote><p>' + text + '</p>' + extra_html
                       + '<a href="' + canonical + '">' + date + '</a></blockquote>'})


class MemoryMonitor:
    """Keep refresh checkpoints in memory, including the state between rounds."""

    def __init__(self, posts, public=None):
        self.posts = copy.deepcopy(posts)
        self.files = {"data/cache/tibo/verified.json": {"posts": copy.deepcopy(posts)},
                      "data/public/tibo.json": copy.deepcopy(public or {"items": [], "references": []})}
        self.identities = list(posts)
        self.responses = {pid: embed(value["text"], pid) for pid, value in posts.items()}
        self.checked = []

    def read(self, path, default=None):
        return copy.deepcopy(self.files.get(path.relative_to(ROOT).as_posix(), default))

    def write(self, path, value):
        self.files[path.relative_to(ROOT).as_posix()] = copy.deepcopy(value)

    def get(self, url, **_kwargs):
        if url in dict(watch.DISCOVERY).values():
            return " ".join("https://x.com/thsottiaux/status/" + pid for pid in self.identities)
        if urllib.parse.urlparse(url).hostname == "publish.twitter.com":
            canonical = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["url"][0]
            identity = canonical.rsplit("/", 1)[1]
            self.checked.append(identity)
            response = self.responses[identity]
            if isinstance(response, Exception):
                raise response
            return response
        raise watch.SourceError("Fixture source unavailable")

    def refresh(self, instant="2026-10-08T00:30:00Z"):
        with patch.object(watch, "read_json", side_effect=self.read), \
                patch.object(watch, "write_json", side_effect=self.write), \
                patch.object(watch, "api_posts", return_value=None), \
                patch.object(watch, "now_iso", return_value=instant):
            return watch.refresh_tibo(ROOT, getter=self.get)


class TiboAnnouncementRegressions(unittest.TestCase):
    def assert_no_grant_or_completion_claim(self, row):
        self.assertNotIn("补发", row["title"])
        self.assertNotIn("完成", row["title"])
        public_assertions = " ".join([row["summary"], *row.get("facts", [])])
        self.assertNotRegex(public_assertions, r"原帖提到补发|正在补发|补发可储存|作者表示刷新已完成|刷新已完成")
        self.assertIsNone(row["reset_at"])

    def test_banked_conditions_and_questions_are_proposals(self):
        examples = [
            "If we give everyone a banked reset, your Codex usage limits would be restored.",
            "Should we give everyone a banked reset in Codex?",
        ]
        for text in examples:
            with self.subTest(text=text):
                row = watch.classify_post(post(text))
                self.assertIsNotNone(row)
                self.assertEqual(row["event_status"], "proposal")
                self.assertEqual(row["mechanism_label"], "可储存重置信息")
                self.assert_no_grant_or_completion_claim(row)

    def test_banked_denial_never_claims_a_grant(self):
        for text in ["We cannot give everyone a banked reset in Codex.",
                     "We will not give a reset in Codex; banked reset grants are not coming."]:
            with self.subTest(text=text):
                row = watch.classify_post(post(text))
                self.assertEqual(row["event_status"], "not_announced")
                self.assertEqual(row["mechanism_label"], "未宣布重置")
                self.assert_no_grant_or_completion_claim(row)

    def test_question_and_conditional_completion_are_proposals(self):
        for text in ["If we have reset all Codex usage limits, your quota should be restored.",
                     "Did we reset all Codex usage limits?"]:
            with self.subTest(text=text):
                row = watch.classify_post(post(text))
                self.assertEqual(row["event_status"], "proposal")
                self.assert_no_grant_or_completion_claim(row)

    def test_explicit_future_reset_remains_an_announcement(self):
        row = watch.classify_post(post("We will reset Codex limits tomorrow at 10am PST."))
        self.assertEqual(row["event_status"], "announced")
        self.assertIsNone(row["reset_at"])
        self.assertIn("10am PST", row["reset_time_text"])
        self.assertNotIn("作者表示刷新已完成", row["summary"])

    def test_other_product_usage_and_quota_do_not_enter_the_column(self):
        for text in ["My GitHub API usage quota resets tomorrow.",
                     "We reset the weekly rate limit of our database.",
                     "GitHub gives users a banked reset for API usage."]:
            with self.subTest(text=text):
                self.assertIsNone(watch.classify_post(post(text)))
        self.assertIsNotNone(watch.classify_post(post("How many banked resets do you have?")))

    def test_publication_date_comes_from_last_canonical_date_anchor(self):
        text = "Codex quota reset is planned for October 9, 2026."
        extra = '<a href="https://x.com/thsottiaux/status/' + POST_ID + '">October 6, 2026</a>'
        verified = watch.verify_oembed(POST_ID, lambda *_a, **_k: embed(text, extra_html=extra))
        self.assertEqual(verified["published_at"], "2026-10-07")
        self.assertEqual(verified["date_precision"], "day")

    def test_other_post_date_and_unlinked_dates_cannot_supply_publication_day(self):
        canonical = "https://x.com/thsottiaux/status/" + POST_ID
        data = {"author_url": "https://x.com/thsottiaux", "url": canonical,
                "html": '<blockquote><p>Codex reset is planned for October 9, 2026.</p>'
                        '<a href="https://x.com/thsottiaux/status/2107913674593644799">October 6, 2026</a>'
                        '<a>October 7, 2026</a></blockquote>'}
        verified = watch.verify_oembed(POST_ID, lambda *_a, **_k: json.dumps(data))
        self.assertIsNone(verified["published_at"])
        self.assertEqual(verified["date_precision"], "unknown")

    def test_successful_recheck_with_unrelated_edit_withdraws_old_fact(self):
        original = post("We reset all Codex limits.")
        old = watch.classify_post(original)
        monitor = MemoryMonitor({POST_ID: original}, {"items": [old], "references": []})
        monitor.responses[POST_ID] = embed("A corrected unrelated coding update.")
        result = monitor.refresh()
        self.assertEqual(result["verified_count"], 1)
        self.assertNotIn(old["id"], {row["id"] for row in result["items"]})
        self.assertGreaterEqual(result["updated_count"], 1)

    def test_failed_recheck_preserves_fact_and_its_original_verification_time(self):
        original = post("We reset all Codex limits.")
        old = watch.classify_post(original)
        last_success = "2026-10-07T01:00:00Z"
        monitor = MemoryMonitor({POST_ID: original}, {"items": [old], "references": [],
                                                         "last_success_at": last_success})
        monitor.responses[POST_ID] = watch.SourceError("Fixture publisher unavailable")
        result = monitor.refresh()
        self.assertEqual(result["items"], [old])
        self.assertEqual(result["last_success_at"], last_success)
        self.assertEqual(result["status"], "unavailable")

    def test_cached_rechecks_cover_all_old_announcements_and_rotate_candidates(self):
        identities = [str(int(POST_ID) + index) for index in range(20)]
        cached = {pid: post("An unrelated coding update.", pid,
                            "2026-10-07T12:" + str(index).zfill(2) + ":00Z")
                  for index, pid in enumerate(identities)}
        for index, pid in enumerate(identities[:3]):
            cached[pid] = post("We reset all Codex usage limits. Confirmation " + str(index) + ".", pid,
                               "2026-10-01T00:" + str(index).zfill(2) + ":00Z")
        old = watch.merge_records([], [watch.classify_post(cached[pid]) for pid in identities[:3]])[0]
        monitor = MemoryMonitor(cached, {"items": old, "references": []})
        for index in range(3):
            monitor.refresh("2026-10-08T00:30:0" + str(index) + "Z")
        self.assertEqual(monitor.checked[0], identities[0])
        self.assertTrue(set(identities[:3]).issubset(monitor.checked))
        self.assertGreater(len(set(monitor.checked)), 8)

    def test_editing_one_post_does_not_hide_a_new_post_with_its_original_body(self):
        original = watch.classify_post(post("We reset all Codex usage limits."))
        edited = watch.classify_post(post("We will reset all Codex usage limits tomorrow."))
        other = watch.classify_post(post("We reset all Codex usage limits.", str(int(POST_ID) + 1)))
        rows, new, updated = watch.merge_records([original], [edited, other])
        self.assertEqual({row["id"] for row in rows}, {edited["id"], other["id"]})
        self.assertEqual((new, updated), (1, 1))
        self.assertEqual({row["id"]: row["event_status"] for row in rows},
                         {edited["id"]: "announced", other["id"]: "completed"})


class TiboSearchRegression(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required to run the actual browser script")
    def test_search_stays_in_the_public_column_with_and_without_a_workspace(self):
        # Execute the actual event handler with a small DOM, rather than matching source text.
        script = r'''
const fs = require("fs"), vm = require("vm");
const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    innerHTML: "", textContent: "", hidden: false, value: "", dataset: {}, handlers: {},
    classList: {add() {}, remove() {}, toggle() {}},
    addEventListener(type, callback) { this.handlers[type] = callback; },
    setAttribute() {}, showModal() {}, close() {}
  });
  return elements.get(selector);
}
const row = title => ({id: title, title, summary: "Public quota information", source: "Tibo",
  published_at: "2026-10-07", date_precision: "day", collected_at: "2026-10-07T01:00:00Z",
  last_verified_at: "2026-10-07T01:00:00Z", event_status: "announced", mechanism_label: "额度刷新"});
const hub = {featured: [], skills: [], growth: [], news: [], repositories: [], skill_count: 0,
  repository_count: 0, updated_at: "2026-10-08T00:30:00Z", tibo: {status: "partial",
  updated_at: "2026-10-08T00:30:00Z", items: [row("Matching announced_item"), row("Other unrelated_item")],
  references: [], sources: []}};
const context = vm.createContext({document: {querySelector: element, querySelectorAll: () => [],
  documentElement: {dataset: {}}, dispatchEvent() {}}, window: {},
  localStorage: {getItem() { return null; }, setItem() {}},
  location: {hash: "", pathname: "/", search: ""}, history: {replaceState() {}},
  CustomEvent: class {}, matchMedia: () => ({matches: true}),
  setInterval() {}, setTimeout() {}, clearTimeout() {},
  fetch: async () => ({ok: true, json: async () => hub}),
  URL, URLSearchParams, Intl, Date, hub});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const results = [];
for (const privateWorkspace of [false, true]) {
  context.privateWorkspace = privateWorkspace;
  vm.runInContext(`state.hub = hub; state.query = ""; state.filter = "tibo";
    state.report = null; state.board = privateWorkspace ? {generated_at: "2026-10-07T01:00:00Z"} : null;
    renderPublic();`, context);
  element("#search").value = "announced_item";
  element("#search").handlers.input({target: element("#search")});
  results.push({privateWorkspace, matchingVisible: element("#content").innerHTML.includes("Matching announced_item"),
    otherVisible: element("#content").innerHTML.includes("Other unrelated_item"),
    personalControlsHidden: element("#editor-note").hidden && element("#personal-sidebar").hidden});
}
process.stdout.write(JSON.stringify(results));
'''
        result = subprocess.run([shutil.which("node"), "-e", script, str(ROOT / "web/app.js")],
                                capture_output=True, text=True, check=True, timeout=20)
        cases = json.loads(result.stdout)
        self.assertEqual(len(cases), 2)
        for case in cases:
            with self.subTest(private_workspace=case["privateWorkspace"]):
                self.assertTrue(case["matchingVisible"])
                self.assertFalse(case["otherVisible"])
                self.assertTrue(case["personalControlsHidden"])


if __name__ == "__main__":
    unittest.main()
