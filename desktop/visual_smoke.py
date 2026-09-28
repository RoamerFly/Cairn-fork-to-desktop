"""Capture the source-mode overview for visual comparison with the mockup."""

from __future__ import annotations

import ctypes
import os
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
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    with tempfile.TemporaryDirectory(prefix="cairn-visual-smoke-") as profile:
        process = subprocess.Popen(
            ["python", str(ROOT / "desktop" / "gui.py")],
            env={**os.environ, "LOCALAPPDATA": profile},
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
            user32.SetForegroundWindow(window)
            time.sleep(7)
            try:
                screenshot = ImageGrab.grab(window=window)
            except OSError:
                rect = wintypes.RECT()
                if not user32.GetWindowRect(window, ctypes.byref(rect)):
                    raise RuntimeError("Could not read GUI window position")
                screenshot = ImageGrab.grab(
                    bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
                )
            screenshot.save(OUTPUT)
        finally:
            process.terminate()
            process.wait(timeout=10)
    print(OUTPUT)


if __name__ == "__main__":
    main()
