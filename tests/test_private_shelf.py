import copy
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from morningpaper.catalog import prepare_catalog
from morningpaper.core import fingerprint, read_json, write_json
from morningpaper.hosts import discover_roots
from morningpaper.personal import board_for_workspace, exact_installed, generate_personal, import_workspace_inventory, validate_matches
from morningpaper.private_store import PrivateStore
from morningpaper.providers import ProviderError, generate_json
from morningpaper.scanner import scan_roots
from morningpaper.shelf_server import ShelfService, make_shelf_handler

PROJECT=Path(__file__).resolve().parents[1]
SOURCE={"id":"1:skills/debug/SKILL.md","name":"systematic-debugging","description":"Find a software bug root cause.","path":"skills/debug/SKILL.md",
        "repository":"owner/repo","url":"https://github.com/owner/repo/blob/abc/skills/debug/SKILL.md","stars":5000,"fingerprint":"version-one",
        "source_fingerprint":"source-one","source_text":"---\nname: systematic-debugging\ndescription: Find a software bug root cause.\n---\nFollow evidence.",
        "general_score":90,"general_reason":"Reusable debugging method","summary":"系统调试","difficulty":"beginner","neutral_status":"ai_reviewed",
        "tags":["coding"],"source_status":"current","evidence_paths":["skills/debug/SKILL.md"]}


def seed_catalog(root):
    write_json(root/"data/public/catalog.json",{"version":"catalog-one","updated_at":"2026-10-06T00:00:00+00:00","items":[SOURCE],
               "repositories":[{"name":"owner/repo","stars":5000,"skill_count":1,"read_count":1,"url":"https://github.com/owner/repo"}]})


class PrivateDataTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.store=PrivateStore(self.root/"private-a");self.other=PrivateStore(self.root/"private-b")
        self.profile=self.store.create_workspace({"name":"开发","host":"codex","goals":"排查软件错误","roots":[]})
        self.profile2=self.store.create_workspace({"name":"研究","host":"generic","goals":"整理资料","roots":[]})
        seed_catalog(self.root)
        for name in ["personal-fit.md","personal-fit.schema.json"]:
            target=self.root/"prompts"/name;target.parent.mkdir(exist_ok=True);target.write_text((PROJECT/"prompts"/name).read_text(encoding="utf-8"),encoding="utf-8")

    def tearDown(self): self.folder.cleanup()

    def test_new_installation_has_no_previous_user_workspaces(self):
        self.assertEqual(self.other.list_workspaces(),[])
        with self.assertRaises(ValueError): self.other.profile(self.profile["id"])
        with self.assertRaises(ValueError): self.store.workspace_dir("../../private-b")

    def test_api_secret_never_saved_in_profile(self):
        p=self.store.create_workspace({"name":"API","provider":{"id":"deepseek"},"session_api_key":"test-secret"})
        self.assertNotIn("test-secret",(self.store.workspace_dir(p["id"])/"profile.json").read_text(encoding="utf-8"))

    def test_workspace_feedback_does_not_affect_another_workspace(self):
        self.store.write(self.profile["id"],"feedback.json",{"id":{"action":"already_have"}})
        self.assertEqual(self.store.read(self.profile2["id"],"feedback.json",{}),{})

    def test_classic_catalog_is_available_before_personal_scan(self):
        board=board_for_workspace(self.store,self.profile["id"],self.root)
        self.assertTrue(board["needs_scan"]);self.assertFalse(board["personal"]);self.assertEqual(board["classics"][0]["name"],"systematic-debugging")

    def test_same_installed_definition_is_covered_without_model_call(self):
        import_workspace_inventory(self.store,self.profile["id"],{"skills":[{"name":SOURCE["name"],"description":SOURCE["description"],"catalog_skill_id":SOURCE["id"],"catalog_fingerprint":SOURCE["fingerprint"]}]})
        with patch("morningpaper.personal.generate_json") as model:
            board=generate_personal(self.store,self.profile["id"],self.root)
        model.assert_not_called();self.assertFalse(board["personal"]);self.assertEqual(board["items"][0]["relation"],"covered")
        self.assertEqual(board["items"][0]["analysis_status"],"inventory_matched")

    def test_same_catalog_id_with_old_version_is_not_assumed_covered(self):
        inventory={"skills":[{"name":SOURCE["name"],"catalog_skill_id":SOURCE["id"],"catalog_fingerprint":"old-version"}]}
        self.assertIsNone(exact_installed(SOURCE,inventory))

    def test_goal_change_invalidates_previous_personal_results(self):
        import_workspace_inventory(self.store,self.profile["id"],{"skills":[],"confirmed_empty":True})
        inventory=self.store.read(self.profile["id"],"inventory.json")
        analysis={"id":SOURCE["id"],"score":90,"relation":"new","category":"gap","compatibility_status":"documented","reason":"debug"}
        self.store.write(self.profile["id"],"matches.json",{"inventory_version":inventory["version"],"profile_version":self.store.profile_version(self.profile),"analyses":{SOURCE["id"]:analysis}})
        self.assertTrue(board_for_workspace(self.store,self.profile["id"],self.root)["personal"])
        self.store.update_workspace(self.profile["id"],{"goals":"整理文档"})
        board=board_for_workspace(self.store,self.profile["id"],self.root)
        self.assertFalse(board["personal"]);self.assertTrue(board["classics"])

    def test_agent_change_requires_new_inventory_scan(self):
        import_workspace_inventory(self.store,self.profile["id"],{"skills":[],"confirmed_empty":True})
        self.store.update_workspace(self.profile["id"],{"host":"deepcode"})
        with self.assertRaises(ValueError): generate_personal(self.store,self.profile["id"],self.root)

    def test_imported_inventory_is_marked_for_preservation(self):
        import_workspace_inventory(self.store,self.profile["id"],{"skills":[],"confirmed_empty":True})
        self.assertEqual(self.store.profile(self.profile["id"])["inventory_mode"],"imported")

    def test_public_export_excludes_all_personal_fields(self):
        candidate={**SOURCE,"reason":"private-business","matched_existing":["private-skill"],"score":99}
        write_json(self.root/"data/state.json",{"repositories":{"owner/repo":{"candidates":{SOURCE["path"]:candidate}}},"history":{"private-user":"secret"}})
        # Force a fresh public export, so no prior neutral record influences the check.
        (self.root/"data/public/catalog.json").unlink()
        prepare_catalog(self.root)
        for name in ["catalog.json","collection.json"]:
            text=(self.root/"data/public"/name).read_text(encoding="utf-8")
            self.assertNotIn("private-business",text);self.assertNotIn("private-skill",text);self.assertNotIn("private-user",text)

    def test_unknown_existing_skill_reference_is_rejected(self):
        result={"analyses":[{"id":SOURCE["id"],"relation":"improvement","category":"improvement","matched_existing":["invented"],"evidence_paths":[SOURCE["path"]]}]}
        with self.assertRaises(ProviderError): validate_matches(result,[SOURCE],{"skills":[]})


class HostScannerTests(unittest.TestCase):
    def test_deepcode_and_codex_project_roots_are_separate(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)/"home";project=Path(d)/"project";home.mkdir();project.mkdir()
            (project/".git").mkdir();(project/".deepcode/skills").mkdir(parents=True);(project/".agents/skills").mkdir(parents=True)
            deep=discover_roots("deepcode",str(project),home,str(home/".codex"))
            codex=discover_roots("codex",str(project),home,str(home/".codex"))
            self.assertTrue(any(".deepcode" in x["path"] for x in deep["roots"] if x["scope"]=="project"))
            self.assertFalse(any(".deepcode" in x["path"] for x in codex["roots"]))

    def test_cursor_plain_markdown_and_codex_disabled_skills(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skill=root/"test";skill.mkdir();path=skill/"SKILL.md"
            path.write_text("# Testing\nRun structured tests.",encoding="utf-8")
            roots=[{"path":str(root),"scope":"user"}]
            self.assertEqual(scan_roots(roots,"cursor")["skills"][0]["name"],"test")
            path.write_text("---\nname: test\ndescription: Run structured tests.\n---\nTest",encoding="utf-8")
            config=root/"config.toml";config.write_text('[[skills.config]]\npath = '+json.dumps(str(path))+'\nenabled = false\n',encoding="utf-8")
            inventory=scan_roots(roots,"codex",str(config))
            self.assertFalse(inventory["skills"][0]["enabled"])
            self.assertEqual(inventory["skills"][0]["availability"],"needs_runtime_check")


class ShelfHttpTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name);seed_catalog(self.root)
        self.store=PrivateStore(self.root/"private");self.profile=self.store.create_workspace({"name":"A","host":"generic"})
        self.profile2=self.store.create_workspace({"name":"B","host":"generic"})
        self.service=ShelfService(self.root,self.store)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),make_shelf_handler(self.service,0));self.port=self.server.server_port
        self.server.RequestHandlerClass=make_shelf_handler(self.service,self.port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base="http://127.0.0.1:"+str(self.port)
        self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.post("/api/session",{"launch_token":self.service.launch_token},csrf=False)
        self.csrf=self.get("/api/bootstrap")["token"]

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.folder.cleanup()

    def get(self,path,workspace=None):
        headers={"X-Workspace-Id":workspace} if workspace else {}
        with self.client.open(urllib.request.Request(self.base+path,headers=headers)) as response:return json.load(response)

    def post(self,path,value,csrf=True,origin=None,workspace=None):
        headers={"Content-Type":"application/json"}
        if csrf:headers["X-Morningpaper-Token"]=self.csrf
        if origin:headers["Origin"]=origin
        if workspace:headers["X-Workspace-Id"]=workspace
        request=urllib.request.Request(self.base+path,data=json.dumps(value).encode(),headers=headers)
        with self.client.open(request) as response:return json.load(response)

    def test_private_get_requires_launch_session(self):
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(self.base+"/api/bootstrap")
        self.assertEqual(error.exception.code,401);error.exception.close()

    def test_public_news_and_skills_readable_without_private_session(self):
        for path in ("/api/public/home","/api/catalog","/api/public/catalog"):
            with urllib.request.urlopen(self.base+path) as response:
                data=json.load(response)
                self.assertEqual(response.status,200)
                self.assertNotIn("workspaces",data)
                self.assertNotIn("instance_id",data)

    def test_other_installation_launch_token_does_not_authenticate(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.post("/api/session",{"launch_token":"another-user"},csrf=False)
        self.assertEqual(error.exception.code,403);error.exception.close()

    def test_cross_origin_operations_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.post("/api/workspaces",{"name":"foreign"},origin="http://127.0.0.1:3000")
        self.assertEqual(error.exception.code,403);error.exception.close()

    def test_feedback_and_selection_are_scoped_to_workspace(self):
        self.post("/api/feedback",{"id":SOURCE["id"],"action":"interested"},workspace=self.profile["id"])
        self.assertTrue(self.get("/api/feedback",self.profile["id"]))
        self.assertFalse(self.get("/api/feedback",self.profile2["id"]))
        self.assertEqual(self.get("/data/leaderboard.json",self.profile2["id"])["workspace_id"],self.profile2["id"])

    def test_arbitrary_workspace_id_is_not_an_access_grant(self):
        other=PrivateStore(self.root/"other-user").create_workspace({"name":"elsewhere"})
        with self.assertRaises(urllib.error.HTTPError) as error:self.get("/data/leaderboard.json",other["id"])
        self.assertEqual(error.exception.code,400);error.exception.close()


if __name__=="__main__":unittest.main()
