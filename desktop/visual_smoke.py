"""Capture the source-mode overview for visual comparison with the mockup."""

from __future__ import annotations

import ctypes
import os
import argparse
import subprocess
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "desktop" / "design" / "cairn-desktop-implemented.png"
TITLE = "Cairn 桌面控制中心"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", action="store_true")
    parser.add_argument("--storage", type=Path)
    args = parser.parse_args()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    with tempfile.TemporaryDirectory(prefix="cairn-visual-smoke-") as profile:
        environment = {**os.environ, "LOCALAPPDATA": profile}
        if args.storage:
            environment["CAIRN_DESKTOP_STORAGE_ROOT"] = str(args.storage.resolve())
        process = subprocess.Popen(
            ["python", "-c", "import gui; gui.main('graph')"] if args.graph else ["python", str(ROOT / "desktop" / "gui.py")],
            cwd=ROOT / "desktop", env=environment,
        )
        try:
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError(f"GUI exited with status {process.returncode}")
                window = user32.FindWindowW(None, TITLE)
                if window:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("GUI window not found")
            time.sleep(7)
            if process.poll() is not None:
                raise RuntimeError(f"GUI exited before capture with status {process.returncode}")
            window = user32.FindWindowW(None, TITLE)
            user32.ShowWindow(window, 9)
            user32.SetForegroundWindow(window)
            time.sleep(1)
            try:
                screenshot = ImageGrab.grab(window=window)
            except OSError:
                rect = wintypes.RECT()
                if not user32.GetWindowRect(window, ctypes.byref(rect)):
                    raise RuntimeError("Could not read GUI window position")
                screenshot = ImageGrab.grab(
                    bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
                )
            if screenshot.width < 500 or screenshot.height < 300 or screenshot.getbbox() is None:
                raise RuntimeError("GUI capture is empty or minimized")
            screenshot.save(OUTPUT)
        finally:
            process.terminate()
            process.wait(timeout=10)
    print(OUTPUT)


if __name__ == "__main__":
    main()
