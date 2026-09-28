"""Build a one-file Windows launcher with the Cairn runtime embedded."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path(__file__).resolve().parent
ZIP_PATH = DESKTOP / "build" / "cairn-runtime.zip"
DIST_PATH = DESKTOP / "dist_windows"


def package_files() -> list[tuple[Path, str]]:
    files = [
        (ROOT / "Dockerfile", "Dockerfile"),
        (ROOT / "dispatch.deepseek-codex.example.yaml", "dispatch.deepseek-codex.example.yaml"),
        (DESKTOP / "cairn-desktop.compose.yaml", "compose.yaml"),
        (ROOT / "cairn" / "pyproject.toml", "cairn/pyproject.toml"),
        (ROOT / "cairn" / "uv.lock", "cairn/uv.lock"),
    ]
    source_root = ROOT / "cairn" / "src"
    files.extend(
        (path, path.relative_to(ROOT).as_posix())
        for path in source_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    return files


def build_payload() -> Path:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(ZIP_PATH, "w", ZIP_DEFLATED) as archive:
        for source, target in package_files():
            archive.write(source, target)
    return ZIP_PATH


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows EXE on Windows.")
    payload = build_payload()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "CairnDesktop",
            "--distpath",
            str(DIST_PATH),
            "--workpath",
            str(DESKTOP / "build" / "pyinstaller"),
            "--specpath",
            str(DESKTOP / "build"),
            "--add-data",
            f"{payload};.",
            str(DESKTOP / "gui.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    print(DIST_PATH / "CairnDesktop.exe")


if __name__ == "__main__":
    main()
