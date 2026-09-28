"""Runtime extraction and configuration helpers for Cairn Desktop."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import ZipFile


APP_TITLE = "Cairn 桌面控制中心"
WORKER_IMAGE = "ghcr.io/oritera/cairn-worker-container:latest"
SERVER_URL = "http://127.0.0.1:8000"
PLACEHOLDER = "REPLACE_WITH_YOUR_DEEPSEEK_API_KEY"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def bundled_payload() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent / "build"))
    return base / "cairn-runtime.zip"


def storage_root() -> Path:
    override = os.environ.get("CAIRN_DESKTOP_STORAGE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False) and (Path(sys.executable).parent / "portable.flag").is_file():
        return Path(sys.executable).parent / "CairnDesktopData"
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "CairnDesktop"


def runtime_root() -> Path:
    return storage_root() / "app"


def data_root() -> Path:
    return storage_root() / "data"


def migrate_legacy_storage(root: Path) -> None:
    """Copy user state from the first desktop build, leaving old data untouched."""
    legacy = root / "runtime"
    data = root / "data"
    if not legacy.is_dir():
        return
    data.mkdir(parents=True, exist_ok=True)
    old_config = legacy / "dispatch.yaml"
    new_config = data / "dispatch.yaml"
    if old_config.is_file() and not new_config.exists():
        shutil.copy2(old_config, new_config)
    old_database = legacy / "datas" / "cairn"
    new_database = data / "cairn"
    if old_database.is_dir() and not new_database.exists():
        shutil.copytree(old_database, new_database)


def ensure_runtime(payload: Path, destination: Path) -> None:
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    stamp = destination / ".payload-sha256"
    if stamp.exists() and stamp.read_text(encoding="ascii") == digest:
        return
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(payload) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Invalid bundled file path")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    stamp.write_text(digest, encoding="ascii")


def make_config(template: str, api_key: str, model: str) -> str:
    api_key = api_key.strip()
    if not api_key or api_key == PLACEHOLDER:
        raise ValueError("请填写 DeepSeek API Key。")
    if model not in {"deepseek-flash", "deepseek-v4-pro"}:
        raise ValueError("请选择受支持的 DeepSeek 模型。")
    result = template.replace(f'OPENAI_API_KEY: "{PLACEHOLDER}"', f"OPENAI_API_KEY: {json.dumps(api_key)}")
    result = result.replace('CODEX_MODEL: "deepseek-flash"', f"CODEX_MODEL: {json.dumps(model)}")
    if result == template or PLACEHOLDER in result:
        raise ValueError("内置配置模板不兼容。")
    return result


def load_saved_settings(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", "deepseek-flash"
    key = ""
    model = "deepseek-flash"
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("OPENAI_API_KEY:"):
            key = json.loads(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("CODEX_MODEL:"):
            model = json.loads(stripped.split(":", 1)[1].strip())
    return key, model


def docker_available() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "未安装 Docker CLI"
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "Linux 引擎不可用"
    if result.returncode != 0 or not result.stdout.strip():
        return False, "Linux 引擎未启动"
    return True, f"已就绪 · {result.stdout.strip()}"


def server_available() -> bool:
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/projects", timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False
