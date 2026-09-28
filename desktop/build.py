"""Build a one-file Windows launcher with the Cairn runtime embedded."""

from __future__ import annotations

import subprocess
import sys
import importlib.metadata
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path(__file__).resolve().parent
ZIP_PATH = DESKTOP / "build" / "cairn-runtime.zip"
DIST_PATH = DESKTOP / "dist_windows"


def package_files() -> list[tuple[Path, str]]:
    files = [
        (ROOT / "LICENSE", "LICENSE"),
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
        notices = ["Cairn desktop dependencies\n", "Source: https://github.com/RoamerFly/Cairn-fork-to-desktop\n"]
        for name in ("pywebview", "pythonnet", "clr_loader", "proxy_tools", "bottle", "typing_extensions", "PyYAML", "cffi", "pycparser"):
            try:
                distribution = importlib.metadata.distribution(name)
            except importlib.metadata.PackageNotFoundError:
                continue
            notices.append(f"\n{name} {distribution.version}\n")
            license_text = distribution.metadata.get("License")
            if license_text:
                notices.append(license_text + "\n")
            for item in distribution.files or []:
                if item.name.lower().startswith(("license", "copying")) and ".dist-info" in str(item):
                    file = distribution.locate_file(item)
                    if file.is_file():
                        notices.append(file.read_text(encoding="utf-8", errors="replace") + "\n")
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
        if python_license.is_file():
            archive.write(python_license, "licenses/Python-LICENSE.txt")
        archive.writestr("licenses/THIRD_PARTY_NOTICES.txt", "\n".join(notices))
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
            "--add-data",
            f"{DESKTOP / 'web'};web",
            "--collect-all",
            "webview",
            str(DESKTOP / "web_main.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    print(DIST_PATH / "CairnDesktop.exe")


if __name__ == "__main__":
    main()
