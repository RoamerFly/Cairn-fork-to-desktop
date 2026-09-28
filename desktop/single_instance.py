"""A Windows named mutex guards the GUI process, and duplicate launches focus it."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


MUTEX_NAME = "Local\\CairnDesktopControlCenterSingleton"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
SW_SHOW = 5


class SingleInstance:
    def __init__(self, window_title: str):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32
        self.handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Could not create application mutex")
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        self.window_title = window_title

    def focus_existing(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        user32.FindWindowW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        user32.SetForegroundWindow.restype = wintypes.BOOL
        # The first process may still be constructing its window.
        for _ in range(20):
            window = user32.FindWindowW(None, self.window_title)
            if window:
                user32.ShowWindow(window, SW_SHOW)
                user32.ShowWindow(window, SW_RESTORE)
                user32.SetForegroundWindow(window)
                return
            time.sleep(0.1)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None
