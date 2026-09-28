"""Offline HTTP adapter checks, no Docker or model calls."""

import json
import os
import shutil
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from core import bundled_payload, ensure_runtime, runtime_root
import test_graph_data as graph_fixtures
from web_host import DesktopHost


class WebHostTests(unittest.TestCase):
    def setUp(self):
        self.fixture = graph_fixtures.GraphDataTests()
        self.fixture.setUp()
        self.environment = patch.dict(os.environ, {"CAIRN_DESKTOP_STORAGE_ROOT": str(self.fixture.root)})
        self.environment.start()
        ensure_runtime(bundled_payload(), runtime_root())
        data = self.fixture.root / "data" / "cairn"
        data.mkdir(parents=True)
        self.db = data / "cairn.db"
        shutil.copyfile(self.fixture.db, self.db)
        stage = self.fixture.root / "output" / "p1" / "workspace" / ".cairn" / "runs" / "explore-1"
        stage.mkdir(parents=True)
        (stage / "task.json").write_text(json.dumps({"phase": "explore", "intent_id": "i2", "duration_ms": 1250}))
        (stage / "stdout.log").write_text("synthetic output", encoding="utf-8")
        self.host = DesktopHost()
        self.host.start()

    def tearDown(self):
        self.host.close()
        self.environment.stop()
        self.fixture.tearDown()

    def get(self, path):
        with urllib.request.urlopen(self.host.url + path) as response:
            return response.read()

    def test_original_ui_assets_and_graph_are_embedded(self):
        shell = self.get("/").decode()
        graph = self.get("/graph").decode()
        self.assertIn("0.5.0", shell)
        self.assertIn("执行记录", graph)
        self.assertIn("cytoscape", graph)
        self.assertIn("startProjectReplay", graph)
        self.assertIn("upstreamCairnApp", self.get("/desktop-assets/graph.js").decode())
        self.assertGreater(len(self.get("/static/vendor/cytoscape.min.js")), 100_000)

    def test_offline_data_and_node_logs_do_not_modify_database(self):
        before = self.db.read_bytes()
        summaries = json.loads(self.get("/projects"))
        detail = json.loads(self.get("/projects/p1"))
        records = json.loads(self.get("/desktop/projects/p1/runs?intent_id=i2"))
        self.assertEqual(summaries[0]["fact_count"], 4)
        self.assertEqual(summaries[0]["intent_count"], 3)
        self.assertIsNone(detail["project"]["reason"])
        self.assertTrue(records["node_linked"])
        self.assertNotIn("directory", records["records"][0])
        output = json.loads(self.get("/desktop/projects/p1/runs/explore-1"))
        self.assertEqual(output["stdout"], "synthetic output")
        self.assertIn("origin: origin", self.get("/projects/p1/export?format=yaml").decode())
        self.assertIn("完成行动 i3", self.get("/projects/p1/export?format=timeline").decode())
        self.assertEqual(self.db.read_bytes(), before)

    def test_mutations_need_token_and_offline_service_returns_useful_error(self):
        url = self.host.url + "/projects/p1/status"
        request = urllib.request.Request(url, method="PUT", data=b'{"status":"stopped"}')
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(request)
        self.assertEqual(denied.exception.code, 403)
        request.add_header("X-Cairn-Token", self.host.token)
        with patch("web_host.SERVER_URL", "http://127.0.0.1:1"):
            with self.assertRaises(urllib.error.HTTPError) as offline:
                urllib.request.urlopen(request)
        self.assertEqual(offline.exception.code, 503)
        self.assertIn("历史记录可查看", offline.exception.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as traversal:
            self.get("/static/../../web_main.py")
        self.assertEqual(traversal.exception.code, 404)

    def test_preferences_are_persisted_outside_random_web_origin(self):
        request = urllib.request.Request(self.host.url + "/desktop/preferences", method="PUT",
            data=b'{"layout_mode":"elk_lr","actor_name":"tester","sidePanelWidth":450}',
            headers={"X-Cairn-Token": self.host.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
        preferences = json.loads(self.get("/desktop/preferences"))
        self.assertEqual(preferences["layout_mode"], "elk_lr")
        self.assertEqual(preferences["sidePanelWidth"], 450)
        self.assertTrue((self.fixture.root / "data" / "ui.json").is_file())


if __name__ == "__main__":
    unittest.main()
