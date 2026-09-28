"""Windows tray integration and orderly desktop shutdown."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import webview


def install_window_lifecycle(window, host, icon_path: Path) -> None:
    from System import Action, EventHandler
    from System.Drawing import Icon
    from System.Windows.Forms import ContextMenuStrip, NotifyIcon, ToolStripMenuItem

    tray_ref = [None]
    tray_icon_ref = [None]
    exiting = threading.Event()
    exit_requested = threading.Lock()

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
        def shutdown():
            try:
                # Finish a control operation already in progress before stopping
                # the Compose services, so an image pull/build cannot race stop.
                while host.service.busy:
                    time.sleep(0.25)
                with host.service.lock:
                    host.service.error = ""
                host.service.action("stop", {})
                while host.service.busy:
                    time.sleep(0.25)
                status = host.service.status()
                if status["error"]:
                    raise RuntimeError(status["error"])
                if status["server"]:
                    raise RuntimeError("服务停止后仍可访问，请在控制中心检查运行状态。")
            except Exception as exc:
                message = str(exc)
                script = "window.closeFailed(" + __import__("json").dumps(message, ensure_ascii=False) + ")"
                on_ui(lambda: window.native.webview.CoreWebView2.ExecuteScriptAsync(script))
                exit_requested.release()
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

    def on_closing(_window):
        if exiting.is_set():
            return True
        # ExecuteScriptAsync schedules the prompt without blocking WebView's UI
        # thread; returning False cancels this native close until the choice runs.
        window.native.webview.CoreWebView2.ExecuteScriptAsync("window.handleNativeClose()")
        return False

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
            def show_prompt():
                tray.Visible = False
                window.show()
                window.native.webview.CoreWebView2.ExecuteScriptAsync("window.handleNativeClose(true)")
            on_ui(show_prompt)

        exit_item.Click += EventHandler(prompt_exit)
        tray.DoubleClick += EventHandler(restore_window)
        tray_ref[0] = tray
        tray_icon_ref[0] = icon

    def on_shown(_window):
        on_ui(initialize_tray)

    window.events.shown += on_shown
    window.events.closing += on_closing
    window.events.closed += on_closed
    host.minimize_to_tray = minimize_to_tray
    host.exit_application = exit_application

