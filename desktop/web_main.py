"""Single-instance Windows desktop shell with the original Cairn graph UI."""

import ctypes
from pathlib import Path

import webview

from core import APP_TITLE, bundled_payload, data_root, ensure_runtime, migrate_legacy_storage, output_root, runtime_root, storage_root
from single_instance import SingleInstance
from web_host import DesktopHost


def main(test_callback=None):
    single = SingleInstance(APP_TITLE)
    if single.already_running:
        single.focus_existing()
        single.close()
        return
    host = None
    try:
        migrate_legacy_storage(storage_root())
        ensure_runtime(bundled_payload(), runtime_root())
        data_root().mkdir(parents=True, exist_ok=True)
        output_root().mkdir(parents=True, exist_ok=True)
        host = DesktopHost()
        host.start()
        screen = webview.screens[0]
        width = min(1440, max(900, screen.width - 70))
        height = min(930, max(620, screen.height - 90))
        window = webview.create_window(APP_TITLE, host.url, width=width, height=height, min_size=(900, 620))
        host.service.action('check', {})
        def started():
            if test_callback:
                test_callback(window, host)
        webview.start(started, gui="edgechromium", private_mode=False,
                      icon=str(Path(__file__).resolve().parent / "assets" / "cairn.ico"),
                      storage_path=str(data_root() / "webview"))
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, f"桌面界面启动失败：{exc}\n请确认已安装 Microsoft Edge WebView2 Runtime。", APP_TITLE, 0x10)
        raise
    finally:
        if host:
            host.close()
        single.close()


if __name__ == "__main__":
    main()
