"""Windows tray integration and orderly desktop shutdown."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from core import data_root


def install_window_lifecycle(window, host, icon_path: Path) -> None:
    from System import Action, EventHandler
    from System.Drawing import Icon
    from System.Windows.Forms import (
        ContextMenuStrip, NotifyIcon, ToolStripMenuItem,
    )

    tray_ref = [None]
    tray_icon_ref = [None]
    exiting = threading.Event()
    exit_requested = threading.Lock()

    def execute_script(script):
        on_ui(lambda: window.native.webview.CoreWebView2.ExecuteScriptAsync(script))

    def on_ui(callback):
        native = window.native
        if native.InvokeRequired:
            native.BeginInvoke(Action(callback))
        else:
            callback()

    def restore_window(_sender=None, _event=None):
        def show():
            if tray_ref[0]:
                tray_ref[0].Visible = False
            window.show()
            window.restore()
        on_ui(show)

    def minimize_to_tray():
        def hide():
            if tray_ref[0] is None:
                return
            tray_ref[0].Visible = True
            window.hide()
        on_ui(hide)

    def exit_application():
        if not exit_requested.acquire(blocking=False):
            return
        execute_script("window.showCloseProgress && window.showCloseProgress()")
        def shutdown():
            try:
                # Finish a control operation already in progress before stopping
                # the Compose services, so an image pull/build cannot race stop.
                while host.service.busy:
                    time.sleep(0.25)
                if exiting.is_set():
                    return
                host.service.stop()
                if host.service.status()["server"]:
                    raise RuntimeError("服务停止后仍可访问，请在控制中心检查运行状态。")
            except Exception as exc:
                message = str(exc)
                script = "window.closeFailed(" + json.dumps(message, ensure_ascii=False) + ")"
                execute_script(script)
                exit_requested.release()
                return
            if exiting.is_set():
                return
            exiting.set()
            def close():
                if tray_ref[0]:
                    tray_ref[0].Visible = False
                    tray_ref[0].Dispose()
                    tray_ref[0] = None
                if tray_icon_ref[0]:
                    tray_icon_ref[0].Dispose()
                    tray_icon_ref[0] = None
                window.destroy()
            on_ui(close)
        threading.Thread(target=shutdown, daemon=True, name="cairn-desktop-shutdown").start()

    def force_exit_application():
        exiting.set()
        on_ui(window.destroy)

    def read_close_preferences():
        path = data_root() / "ui.json"
        try:
            preferences = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(preferences, dict):
                return preferences
        except (OSError, ValueError):
            pass
        return {"remember_close": False, "close_behavior": "ask"}

    def handle_close_request():
        preferences = read_close_preferences()
        choice = preferences.get("close_behavior", "ask")
        if preferences.get("remember_close") and choice in {"exit", "tray"}:
            if choice == "tray":
                minimize_to_tray()
            else:
                exit_application()
        else:
            execute_script("window.showCloseDialog && window.showCloseDialog()")
        return False

    def on_closing(_window=None):
        if exiting.is_set() or getattr(host, "test_force_close", False):
            return True
        return handle_close_request()

    def on_closed(_window=None):
        if tray_ref[0]:
            tray_ref[0].Visible = False
            tray_ref[0].Dispose()
            tray_ref[0] = None
        if tray_icon_ref[0]:
            tray_icon_ref[0].Dispose()
            tray_icon_ref[0] = None

    def initialize_tray():
        tray = NotifyIcon()
        icon = Icon(str(icon_path))
        tray.Icon = icon
        tray.Text = "Cairn 桌面控制中心"
        menu = ContextMenuStrip()
        restore = ToolStripMenuItem("打开 Cairn")
        exit_item = ToolStripMenuItem("退出并停止服务")
        menu.Items.Add(restore)
        menu.Items.Add(exit_item)
        tray.ContextMenuStrip = menu
        restore.Click += EventHandler(restore_window)

        def prompt_exit(_sender=None, _event=None):
            tray.Visible = False
            exit_application()

        exit_item.Click += EventHandler(prompt_exit)
        tray.DoubleClick += EventHandler(restore_window)
        tray_ref[0] = tray
        tray_icon_ref[0] = icon

    def on_shown(_window=None):
        if tray_ref[0] is None:
            on_ui(initialize_tray)

    window.events.shown += on_shown
    window.events.closing += on_closing
    window.events.closed += on_closed
    host.minimize_to_tray = minimize_to_tray
    host.restore_window = restore_window
    host.exit_application = exit_application
    host.force_exit_application = force_exit_application
