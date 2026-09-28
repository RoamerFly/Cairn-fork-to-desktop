"""Test the actual WebView2 desktop UI with a fixture or existing offline history."""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from test_graph_data import GraphDataTests
from findings import _source_hash
from web_main import main as run_desktop

OUTPUT = Path(__file__).resolve().parent / "design" / "cairn-desktop-implemented.png"
SETTINGS_OUTPUT = OUTPUT.with_name("cairn-settings-implemented.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", type=Path)
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    fixture = None
    if args.storage:
        storage = args.storage.resolve()
    else:
        fixture = GraphDataTests()
        fixture.setUp()
        storage = fixture.root
        (storage / "data" / "cairn").mkdir(parents=True)
        shutil.copyfile(fixture.db, storage / "data" / "cairn" / "cairn.db")
        with sqlite3.connect(storage / "data" / "cairn" / "cairn.db") as conn:
            conn.execute("UPDATE intents SET created_at='2026-01-01T00:00:01Z', concluded_at='2026-01-01T00:00:02Z'")
            conn.execute("UPDATE facts SET description='未经登录请求 GET /example 返回 HTTP 200，响应包含测试资料。' WHERE id='f2'")
        conn.close()
        import json
        report = storage / "output" / "p1" / "workspace" / ".cairn" / "findings" / "f2.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"fact_id": "f2", "source_hash": _source_hash(
            {"description": "未经登录请求 GET /example 返回 HTTP 200，响应包含测试资料。"}, {"description": "action"}),
            "findings": [{"title": "未授权读取测试资料", "category": "访问控制", "location": "GET /example",
                          "summary": "未经登录即可取得测试资料。", "impact": "测试资料可被未授权访问。",
                          "evidence": ["未经登录请求返回 HTTP 200，响应包含测试资料。"],
                          "reproduction": [{"action": "在未登录状态请求 GET /example", "expected": "HTTP 200，响应包含测试资料"}],
                          "limitations": "仅有这一次请求的记录。"}]}, ensure_ascii=False), encoding="utf-8")
        stage = storage / "output" / "p1" / "workspace" / ".cairn" / "runs" / "explore-1"
        stage.mkdir(parents=True)
        (stage / "task.json").write_text('{"intent_id":"i2","phase":"explore","worker":"fixture","duration_ms":1250}', encoding="utf-8")
        (stage / "stdout.log").write_text("synthetic process output", encoding="utf-8")
        try:
            # Own the test directory outside the UI process: WebView2 releases
            # its browser profile when that process exits.
            result = subprocess.run([sys.executable, __file__, "--storage", str(storage), "--fixture"], timeout=60)
            if result.returncode:
                raise RuntimeError(f"WebView fixture process exited with {result.returncode}")
        finally:
            fixture.tearDown()
        return
    failures = []

    def interact(window, host):
        def js(script):
            return window.evaluate_js(script)

        def wait_for(script, timeout=25):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if js(script):
                    return
                time.sleep(0.1)
            raise AssertionError(f"UI condition timed out: {script}")

        prefix = "document.getElementById('graph').contentWindow.desktopGraphApp"
        try:
            wait_for(f"!!document.getElementById('graph')?.contentWindow?.desktopGraphApp")
            wait_for("initialized")
            if args.fixture:
                js("show('settings'); true")
                wait_for("!document.getElementById('settings').classList.contains('hidden')")
                js("document.getElementById('key').value='sk-fixture-secret'; document.getElementById('output-language').value='en'; action('save'); true")
                wait_for("document.getElementById('current-language').textContent === 'English'")
                wait_for("!jobPending")
                assert host.service.output_language == 'en'
                assert 'sk-fixture-secret' not in js("document.getElementById('logs').textContent")
                js("document.getElementById('output-language').value='zh-CN'; action('save'); true")
                wait_for("document.getElementById('current-language').textContent === '简体中文'")
                js("document.getElementById('layout').value='dagre_lr'; document.getElementById('panel-width').value='460'; document.getElementById('actor').value='测试用户'; savePreferences(); true")
                wait_for(f"{prefix}.layoutMode === 'dagre_lr' && {prefix}.sidePanelWidth === 460")
                js("show('control'); show('settings'); true")
                wait_for("document.getElementById('layout').value === 'dagre_lr'")
                # Restore the graph defaults used by the rest of this smoke.
                js("document.getElementById('layout').value='klay_tb'; document.getElementById('panel-width').value='390'; savePreferences(); true")
                wait_for(f"{prefix}.layoutMode === 'klay_tb'")
            js("show('graph')")
            projects = host.summaries()
            assert projects, "No historical projects to display"
            import json
            js(f"{prefix}.openProject({json.dumps(projects[0]['id'])}); true")
            wait_for(f"!!{prefix}.cy && {prefix}.cy.nodes().length > 0")
            time.sleep(1)
            assert js(f"{prefix}.layoutMode") == "klay_tb"
            if args.fixture:
                assert js(f"{prefix}.cy.nodes().length") == 4  # Completed intents are edges upstream.
                assert js(f"{prefix}.cy.edges().length") == 4
                js(f"{prefix}.cy.edges().filter(e=>e.data('intentId')==='i2').first().emit('tap'); true")
                wait_for(f"{prefix}.selectedNode?.id === 'i2'")
                js(f"{prefix}.sideTab='records'; {prefix}.loadDesktopRecords(); true")
                wait_for(f"{prefix}.desktopRecordsLinked && {prefix}.desktopOutput.stdout.includes('synthetic process output')")
                assert js(f"{prefix}.desktopSelectedRecord().duration_ms") == 1250
                js(f"{prefix}.selectFact('f2'); true")
                wait_for(f"{prefix}.desktopRecordsLinked")
                js(f"{prefix}.sideTab='detail'; {prefix}.layoutMode='elk_lr'; {prefix}.applySelectedLayout(); true")
                wait_for(f"{prefix}.desktopFinding?.available")
                assert js("document.getElementById('graph').contentDocument.body.innerText.includes('未授权读取测试资料')")
                assert js("document.getElementById('graph').contentDocument.body.innerText.includes('复现')")
                time.sleep(1)
                js(f"{prefix}.layoutMode='dagre_tb'; {prefix}.applySelectedLayout(); true")
                time.sleep(1)
                js(f"{prefix}.startProjectReplay(); true")
                wait_for(f"{prefix}.replay.active")
                js(f"{prefix}.exitProjectReplay(); true")
                wait_for(f"!{prefix}.replay.active && !!{prefix}.cy")
                js(f"{prefix}.selectFact('f2'); {prefix}.sideTab='detail'; true")
                time.sleep(1)
            else:
                js(f"{prefix}.selectFact('f001'); true")
                js(f"{prefix}.sideTab='detail'; true")
            # Polling without new graph elements must preserve the user's viewport.
            js(f"{prefix}.cy.zoom(1.3); {prefix}.cy.pan(document.getElementById('graph').contentWindow.JSON.parse('{{\"x\":45,\"y\":35}}')); {prefix}.updateGraph(); true")
            assert abs(js(f"{prefix}.cy.zoom()") - 1.3) < 0.01
            pan_x = js(f"{prefix}.cy.pan().x")
            assert abs(pan_x - 45) < 0.01, f"Viewport changed to {pan_x}"
            js(f"{prefix}.layoutMode='klay_tb'; {prefix}.applySelectedLayout(); true")
            time.sleep(1.3)
            # Capture only this application's WebView, independent of which
            # other application has foreground focus on the user's desktop.
            from System import Action
            from System.IO import FileStream, FileMode
            from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
            stream = FileStream(str(OUTPUT), FileMode.Create)
            tasks = []
            def capture():
                tasks.append(window.native.webview.CoreWebView2.CapturePreviewAsync(
                    CoreWebView2CapturePreviewImageFormat.Png, stream))
            window.native.Invoke(Action(capture))
            try:
                assert tasks[0].Wait(10000), "WebView capture timed out"
            finally:
                stream.Dispose()
            with Image.open(OUTPUT) as image:
                assert image.width > 500 and image.height > 300
            js("show('settings'); true")
            time.sleep(0.5)
            stream = FileStream(str(SETTINGS_OUTPUT), FileMode.Create)
            tasks.clear()
            window.native.Invoke(Action(capture))
            try:
                assert tasks[0].Wait(10000), "Settings capture timed out"
            finally:
                stream.Dispose()
            print("WebView2 smoke passed: upstream graph, layouts, replay, node logs, preserved viewport")
            print("Settings smoke passed: language/key persistence, live graph preferences, icon")
            print(OUTPUT)
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            host.test_force_close = True
            window.destroy()

    try:
        with patch.dict(os.environ, {"CAIRN_DESKTOP_STORAGE_ROOT": str(storage)}):
            run_desktop(test_callback=interact)
    finally:
        if fixture:
            fixture.tearDown()
    if failures:
        raise AssertionError(failures[0])


if __name__ == "__main__":
    main()
