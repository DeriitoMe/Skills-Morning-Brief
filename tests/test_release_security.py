import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from morningpaper.catalog import catalog_public, prepare_catalog
from morningpaper.collect import HttpClient, is_skill_path
from morningpaper.launcher import reader_record
from morningpaper.core import ROOT, read_json, write_json
from morningpaper.network import SafeRedirectHandler, urlopen
from morningpaper.private_store import PrivateStore
from morningpaper.public_monitor import public_home
from morningpaper.runner import run_lock
from morningpaper.shelf_daily import refresh_all
from morningpaper.shelf_server import LocalHTTPServer


class ReleaseSecurityTests(unittest.TestCase):
    def test_popular_skill_repositories_need_no_literal_skills_directory(self):
        self.assertTrue(is_skill_path("code-review/SKILL.md"))
        self.assertTrue(is_skill_path(".claude/skills/debug/SKILL.md"))
        self.assertFalse(is_skill_path("examples/debug/SKILL.md"))

    def test_another_reader_cannot_bind_an_occupied_local_port(self):
        server = LocalHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError): LocalHTTPServer(("127.0.0.1", server.server_port), BaseHTTPRequestHandler)
        finally:
            server.server_close()
    def test_github_cli_login_is_reused_in_memory_only(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True), patch("morningpaper.collect.shutil.which", return_value="gh"), patch("morningpaper.collect.subprocess.run", return_value=CompletedProcess([], 0, "test-key", "")) as command:
            client = HttpClient(Path(folder))
            self.assertEqual(client.token, "test-key")
            self.assertEqual(command.call_args.args[0], ["gh", "auth", "token", "--hostname", "github.com"])
            self.assertEqual(list(Path(folder).rglob("*")), [])

    def test_other_source_checkout_is_not_reused_as_this_reader(self):
        import io
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); store = PrivateStore(root / "private")
            write_json(store.root / "reader-session.json", {"instance_id": store.instance_id, "port": 8765})
            response = io.BytesIO(json.dumps({"instance_id": store.instance_id, "project_id": "another-checkout"}).encode())
            with patch("morningpaper.launcher.urllib.request.urlopen", return_value=response):
                self.assertIsNone(reader_record(store, root))

    def test_catalog_export_is_allowlisted_at_every_level(self):
        original = {"api_key": "private-marker", "items": [{"name": "public", "source_text": "raw", "goals": "private-marker"}],
                    "repositories": [{"name": "owner/repo", "workspace_id": "private-marker"}]}
        exported = catalog_public(original)
        self.assertNotIn("private-marker", json.dumps(exported))
        self.assertNotIn("source_text", exported["items"][0])

    def test_news_and_repository_metadata_cannot_bypass_home_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "data/public/catalog.json", {"items": [], "repositories": [{"name": "owner/repo", "roots": "private-marker"}]})
            write_json(root / "data/public/news.json", {"items": [{"title": "public", "goals": "private-marker"}],
                        "sources": [{"source": "official", "session_api_key": "private-marker"}]})
            self.assertNotIn("private-marker", json.dumps(public_home(root)))

    def test_authenticated_redirect_never_reaches_second_server(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                received.append(self.path)
                self.send_response(302 if self.path == "/start" else 200)
                if self.path == "/start": self.send_header("Location", "/target")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            request = urllib.request.Request("http://127.0.0.1:" + str(server.server_port) + "/start", headers={"Authorization": "Bearer test-key"})
            with self.assertRaises(urllib.error.HTTPError) as caught: urlopen(request)
            caught.exception.close()
            self.assertEqual(received, ["/start"])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_https_downgrade_is_rejected(self):
        request = urllib.request.Request("https://example.com/start")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            SafeRedirectHandler().redirect_request(request, None, 302, "Found", {}, "http://example.com/target")
        caught.exception.close()

    def test_monitor_respects_an_active_process_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with run_lock(root), patch("morningpaper.shelf_daily._refresh_all") as work:
                with self.assertRaises(RuntimeError): refresh_all(root, personal=False)
                work.assert_not_called()

    def test_failed_run_is_recorded_without_raw_exception_or_private_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("morningpaper.shelf_daily._refresh_all", side_effect=OSError("private-marker")):
                with self.assertRaises(OSError): refresh_all(root, personal=False)
            record = read_json(root / ".runtime/latest-monitor.json")
            self.assertEqual(record["status"], "failed")
            self.assertNotIn("private-marker", json.dumps(record))
            self.assertFalse((root / "data/locks/daily.lock").exists())

    def test_degraded_network_run_is_recorded_and_keeps_existing_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "data/public/catalog.json", {"items": [{"name": "existing"}]})
            result = {"sources": [{"source": "repo", "status": "failed"}], "news_sources": [], "requests": 1,
                      "public_editor": "pending", "public_news": 1, "workspaces": [{"name": "private-marker"}]}
            with patch("morningpaper.shelf_daily._refresh_all", return_value=result): refresh_all(root, personal=False)
            record = read_json(root / ".runtime/latest-monitor.json")
            self.assertEqual(record["status"], "degraded")
            self.assertNotIn("private-marker", json.dumps(record))
            self.assertEqual(read_json(root / "data/public/catalog.json")["items"][0]["name"], "existing")

    def test_clean_install_restores_public_seed_without_personal_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "seeds/catalog.json", {"items": [{"id": "one", "name": "public", "fingerprint": "v", "repository": "owner/repo"}]})
            prepare_catalog(root)
            self.assertEqual(read_json(root / "data/public/catalog.json")["items"][0]["name"], "public")
            self.assertEqual(PrivateStore(root / "private").list_workspaces(), [])
