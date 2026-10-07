import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from morningpaper.private_store import PrivateStore
from morningpaper.server import make_handler


class CompatibilityReaderTests(unittest.TestCase):
    def test_compatibility_entry_point_cannot_expose_old_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "web/data").mkdir(parents=True)
            (root / "web/data/inventory.json").write_text('{"secret":"private-marker"}', encoding="utf-8")
            store = PrivateStore(root / "private")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, 0, store))
            server.RequestHandlerClass = make_handler(root, server.server_port, store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:" + str(server.server_port)
            try:
                for path in ("/data/inventory.json", "/api/bootstrap", "/api/saved", "/api/report/old"):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(base + path)
                    self.assertEqual(caught.exception.code, 401)
                    caught.exception.close()
                with urllib.request.urlopen(base + "/api/public/home") as response:
                    self.assertNotIn("private-marker", response.read().decode())
            finally:
                server.shutdown(); server.server_close(); thread.join()
