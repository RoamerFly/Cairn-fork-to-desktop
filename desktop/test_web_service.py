"""Desktop control operations with fake Docker calls and no external requests."""

import os
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import data_root, runtime_root
from web_service import DesktopService


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"CAIRN_DESKTOP_STORAGE_ROOT": self.temporary.name})
        self.environment.start()
        runtime_root().mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "dispatch.deepseek-codex.example.yaml",
                        runtime_root() / "dispatch.deepseek-codex.example.yaml")
        self.service = DesktopService()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_saved_key_reused_and_status_never_returns_secret(self):
        self.service.save({"api_key": "sk-fixture-secret", "model": "deepseek-flash"})
        self.service.save({"api_key": "", "model": "deepseek-v4-pro"})
        with patch("web_service.server_available", return_value=False):
            state = self.service.status()
        self.assertNotIn("sk-fixture-secret", str(state))
        self.assertTrue(state["key_configured"])
        self.assertEqual(state["model"], "deepseek-v4-pro")
        self.assertIn("sk-fixture-secret", (data_root() / "dispatch.yaml").read_text())
        self.service.log("sk-fixture-secret should be removed")
        self.assertIn("[API KEY]", self.service.logs[-1])

    def test_output_language_validates_and_survives_restart(self):
        self.service.save({"api_key": "sk-fixture-secret", "output_language": "en"})
        self.assertEqual(DesktopService().output_language, "en")
        original = (data_root() / "dispatch.yaml").read_bytes()
        with self.assertRaises(ValueError):
            self.service.save({"output_language": "invalid"})
        self.assertEqual((data_root() / "dispatch.yaml").read_bytes(), original)
        self.service.save({"output_language": "zh-CN"})
        self.assertEqual(DesktopService().output_language, "zh-CN")

    def test_start_reuses_image_and_only_pulls_if_missing(self):
        body = {"api_key": "sk-fixture-secret", "model": "deepseek-flash"}
        with patch("web_service.docker_available", return_value=(True, "ready")), \
             patch("web_service.subprocess.run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(self.service, "command") as command:
            self.service.start(body)
            self.assertEqual(command.call_count, 1)
            self.assertIn("up", command.call_args.args[0])
        with patch("web_service.docker_available", return_value=(True, "ready")), \
             patch("web_service.subprocess.run", return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(self.service, "command") as command:
            self.service.start(body)
            self.assertEqual(command.call_count, 2)
            self.assertEqual(command.call_args_list[0].args[0][:2], ["docker", "pull"])

    def test_open_project_uses_sidecar_and_rejects_traversal(self):
        with patch("web_service.os.startfile", create=True) as opened:
            self.service.action("open_project", {"project_id": "proj_001"})
            self.assertEqual(opened.call_args.args[0], Path(self.temporary.name) / "output" / "proj_001")
            with self.assertRaises(ValueError):
                self.service.action("open_project", {"project_id": "../../outside"})


if __name__ == "__main__":
    unittest.main()
