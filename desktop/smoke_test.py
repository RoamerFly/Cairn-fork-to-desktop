"""Smoke test the packaged EXE without requiring a running Docker engine."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "desktop" / "dist_windows" / "CairnDesktop.exe"
LAUNCHER = ROOT / "desktop" / "core.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("cairn_desktop_launcher", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    launcher = load_launcher()
    assert EXE.is_file(), EXE
    payload = ROOT / "desktop" / "build" / "cairn-runtime.zip"
    with tempfile.TemporaryDirectory(prefix="cairn-desktop-smoke-") as temporary:
        base = Path(temporary)
        runtime = base / "CairnDesktop" / "app"
        data = base / "CairnDesktop" / "data"
        launcher.ensure_runtime(payload, runtime)
        assert (runtime / "compose.yaml").is_file()
        assert (runtime / "cairn" / "src" / "cairn" / "server" / "app.py").is_file()
        template = (runtime / "dispatch.deepseek-codex.example.yaml").read_text(encoding="utf-8")
        config = launcher.make_config(template, "sk-test-value", "deepseek-flash")
        assert "sk-test-value" in config and launcher.PLACEHOLDER not in config
        legacy = base / "CairnDesktop" / "runtime"
        (legacy / "datas" / "cairn").mkdir(parents=True)
        (legacy / "dispatch.yaml").write_text(config, encoding="utf-8")
        (legacy / "datas" / "cairn" / "cairn.db").write_bytes(b"legacy")
        launcher.migrate_legacy_storage(base / "CairnDesktop")
        data.mkdir(parents=True, exist_ok=True)
        assert launcher.load_saved_settings(data / "dispatch.yaml") == ("sk-test-value", "deepseek-flash")
        assert (data / "cairn" / "cairn.db").read_bytes() == b"legacy"
        assert (legacy / "datas" / "cairn" / "cairn.db").is_file()
        subprocess.run(
            ["docker", "compose", "-f", "compose.yaml", "config", "--quiet"],
            cwd=runtime,
            check=True,
            capture_output=True,
            text=True,
        )
        # A fresh profile proves that the one-file EXE can launch and unpack its
        # runtime without a system Python installation or a live Docker engine.
        fresh_profile = base / "fresh-profile"
        fresh_profile.mkdir()
        exe_runtime = fresh_profile / "CairnDesktop" / "app"
        environment = {**os.environ, "LOCALAPPDATA": str(fresh_profile)}
        process = subprocess.Popen([str(EXE)], env=environment)
        try:
            for _ in range(80):
                if process.poll() is not None:
                    raise RuntimeError(f"EXE exited unexpectedly: {process.returncode}")
                if (exe_runtime / ".payload-sha256").is_file():
                    assert (exe_runtime / "compose.yaml").is_file()
                    assert (exe_runtime / "cairn" / "src" / "cairn" / "server" / "app.py").is_file()
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("EXE did not extract its runtime")
            time.sleep(1)
            duplicate = subprocess.run(
                [str(EXE)], env=environment, timeout=15, capture_output=True
            )
            assert duplicate.returncode == 0, duplicate.returncode
            assert process.poll() is None, "Primary GUI exited after duplicate launch"
        finally:
            # PyInstaller one-file mode runs a child GUI process. Kill that child
            # with the bootloader parent so its singleton mutex is released.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
            process.wait(timeout=10)
    print(f"Smoke test passed: {EXE} ({EXE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
