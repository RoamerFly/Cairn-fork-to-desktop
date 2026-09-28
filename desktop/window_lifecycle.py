"""Windows tray integration and orderly desktop shutdown."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import webview
from core import data_root


def install_window_lifecycle(window, host, icon_path: Path) -> None:
    from System import Action, EventHandler
    from System.Drawing import Icon, Point, Size
    from System.Windows.Forms import (
        Button, CheckBox, ContextMenuStrip, DialogResult, Form, FormBorderStyle,
        FormStartPosition, Label, NotifyIcon, ToolStripMenuItem,
    )

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

    def read_close_preferences():
        path = data_root() / "ui.json"
        try:
            preferences = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(preferences, dict):
                return preferences
        except (OSError, ValueError):
            pass
        return {"remember_close": False, "close_behavior": "ask"}

    def save_close_preference(choice):
        path = data_root() / "ui.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        preferences = read_close_preferences()
        preferences.update(remember_close=True, close_behavior=choice)
        staged = path.with_suffix(".tmp")
        staged.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")
        staged.replace(path)

    def ask_close_choice():
        dialog = Form()
        dialog.Text = "关闭 Cairn 桌面控制中心？"
        dialog.FormBorderStyle = FormBorderStyle.FixedDialog
        dialog.StartPosition = FormStartPosition.CenterScreen
        dialog.ClientSize = Size(520, 230)
        dialog.MinimizeBox = False
        dialog.MaximizeBox = False
        dialog.ShowInTaskbar = False

        description = Label()
        description.Text = "退出会停止 Cairn 服务和正在运行的任务。\n最小化到托盘会隐藏窗口，并让服务继续运行。"
        description.Location = Point(22, 20)
        description.Size = Size(475, 58)
        dialog.Controls.Add(description)

        remember = CheckBox()
        remember.Text = "记住此选项（可在设置中更改）"
        remember.Location = Point(22, 87)
        remember.Size = Size(300, 28)
        dialog.Controls.Add(remember)

        choice = ["continue"]
        buttons = [
            ("退出并停止服务", "exit", 22),
            ("最小化到托盘", "tray", 190),
            ("继续使用", "continue", 358),
        ]
        for title, value, x in buttons:
            button = Button()
            button.Text = title
            button.Location = Point(x, 145)
            button.Size = Size(145, 38)
            button.DialogResult = DialogResult.OK
            button.Click += EventHandler(lambda _sender, _event, selected=value: choice.__setitem__(0, selected))
            dialog.Controls.Add(button)
        dialog.CancelButton = next(control for control in dialog.Controls if control.Text == "继续使用")
        result = dialog.ShowDialog(window.native)
        return (choice[0] if result == DialogResult.OK else "continue", bool(remember.Checked))

    def handle_close_request():
        preferences = read_close_preferences()
        choice = preferences.get("close_behavior", "ask")
        if preferences.get("remember_close") and choice in {"exit", "tray"}:
            selected, remember = choice, False
        else:
            selected, remember = ask_close_choice()
        if selected == "continue":
            return False
        if remember:
            try:
                save_close_preference(selected)
            except OSError as exc:
                from System.Windows.Forms import MessageBox
                MessageBox.Show(f"无法保存关闭选项：{exc}", "Cairn 桌面控制中心")
        if selected == "tray":
            minimize_to_tray()
        else:
            exit_application()
        return False

    def on_closing(_window):
        if exiting.is_set():
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

    def on_shown(_window):
        on_ui(initialize_tray)

    window.events.shown += on_shown
    window.events.closing += on_closing
    window.events.closed += on_closed
    host.minimize_to_tray = minimize_to_tray
    host.exit_application = exit_application
