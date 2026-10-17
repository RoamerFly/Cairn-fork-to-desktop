"""Portable runtime updates are complete or leave the old runtime intact."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from core import ensure_runtime


class RuntimeUpdateTests(unittest.TestCase):
    def test_upgrade_replaces_tree_and_removes_obsolete_files(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            payload = folder / "payload.zip"
            runtime = folder / "app"
            with ZipFile(payload, "w") as archive:
                archive.writestr("old.txt", "v1")
            ensure_runtime(payload, runtime)
            with ZipFile(payload, "w") as archive:
                archive.writestr("new.txt", "v2")
            ensure_runtime(payload, runtime)
            self.assertFalse((runtime / "old.txt").exists())
            self.assertEqual((runtime / "new.txt").read_text(), "v2")
            self.assertEqual(list(folder.glob(".app.*")), [])

    def test_bad_archive_preserves_existing_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            runtime = folder / "app"
            runtime.mkdir()
            (runtime / "safe.txt").write_text("keep")
            payload = folder / "payload.zip"
            with ZipFile(payload, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            with self.assertRaises(ValueError):
                ensure_runtime(payload, runtime)
            self.assertEqual((runtime / "safe.txt").read_text(), "keep")
            self.assertFalse((folder / "escape.txt").exists())
            self.assertEqual(list(folder.glob(".app.*")), [])

    def test_failed_swap_restores_old_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            runtime = folder / "app"
            runtime.mkdir()
            (runtime / "safe.txt").write_text("old")
            payload = folder / "payload.zip"
            with ZipFile(payload, "w") as archive:
                archive.writestr("new.txt", "new")
            original_replace = Path.replace
            def fail_stage(path, target):
                if ".stage-" in path.name:
                    raise OSError("simulated swap failure")
                return original_replace(path, target)
            with patch.object(Path, "replace", fail_stage):
                with self.assertRaisesRegex(OSError, "simulated swap failure"):
                    ensure_runtime(payload, runtime)
            self.assertEqual((runtime / "safe.txt").read_text(), "old")
            self.assertFalse((runtime / "new.txt").exists())
            self.assertEqual(list(folder.glob(".app.*")), [])
