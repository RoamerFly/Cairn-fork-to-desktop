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
CLOSE_OUTPUT = OUTPUT.with_name("cairn-close-implemented.png")
FACT_OUTPUT = OUTPUT.with_name("cairn-original-fact-implemented.png")
FINDING_OUTPUT = OUTPUT.with_name("cairn-finding-implemented.png")


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
                          "limitations": "仅有这一次请求的记录。"},
                         {"title": "第二条测试发现", "category": "配置检查", "location": "GET /sample",
                          "summary": "用于验证多漏洞标签切换。", "impact": "测试影响。",
                          "evidence": ["测试证据"],
                          "reproduction": [{"action": "请求 GET /sample", "expected": "观察测试响应"}],
                          "limitations": "仅用于界面测试。"}]}, ensure_ascii=False), encoding="utf-8")
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
            screen = __import__('webview').screens[0]
            bounds = window.native.Bounds
            assert abs((bounds.Left + bounds.Width / 2) - (screen.physical_x + screen.physical_width / 2)) < 110, f"horizontal: bounds={bounds}, screen={screen}"
            assert abs((bounds.Top + bounds.Height / 2) - (screen.physical_y + screen.physical_height / 2)) < 110, f"vertical: bounds={bounds}, screen={screen}"
            if args.fixture:
                wait_for("!jobPending")
                if not host.service.status()["server"]:
                    wait_for("document.querySelector('[data-job=\"stop\"]').disabled")
                    host.service.compose_running = True
                    js("status(); true")
                    wait_for("!document.querySelector('[data-job=\"stop\"]').disabled")
                    host.service.compose_running = False
                    js("status(); true")
                    wait_for("document.querySelector('[data-job=\"stop\"]').disabled")
                js("window.__realRequest=request; window.__statusFailures=0; window.__actionDone=false; request=async(path,method,body)=>{if(path==='/desktop/status'){window.__statusFailures++;throw new Error('模拟状态故障')}if(path==='/desktop/action')return {accepted:true};return window.__realRequest(path,method,body)}; action('check').then(()=>window.__actionDone=true); true")
                wait_for("window.__actionDone && !jobPending", timeout=10)
                assert js("window.__statusFailures >= 6")
                js("request=window.__realRequest; status(); true")
                wait_for("document.getElementById('state').textContent !== '状态连接中断'")
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
            project = (next((item for item in projects if any(fact['id'] == 'f001' for fact in host.detail(item['id'])['facts'])), projects[0])
                       if not args.fixture else projects[0])
            js(f"{prefix}.openProject({json.dumps(project['id'])}); true")
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
                wait_for("document.getElementById('graph').contentDocument.body.innerText.includes('查看结果（2 条）')")
                js("Array.from(document.getElementById('graph').contentDocument.querySelectorAll('button')).find(b=>b.innerText.includes('查看结果（2 条）')).click(); true")
                wait_for(f"{prefix}.desktopFindingModalOpen")
                wait_for("document.getElementById('graph').contentDocument.querySelector('[aria-label=\"漏洞整理结果\"]')?.offsetHeight > 300")
                assert js(f"{prefix}.desktopSelectedFinding().title === '未授权读取测试资料'")
                js("Array.from(document.getElementById('graph').contentDocument.querySelectorAll('[aria-label=\"漏洞内容\"] button')).find(b=>b.innerText==='复现步骤').click(); true")
                wait_for("document.getElementById('graph').contentDocument.querySelector('[aria-label=\"漏洞整理结果\"]')?.innerText.includes('在未登录状态请求')")
                js("document.getElementById('graph').contentDocument.querySelectorAll('[aria-label=\"漏洞\"] button')[1].click(); true")
                wait_for("document.getElementById('graph').contentDocument.querySelector('[aria-label=\"漏洞整理结果\"]')?.innerText.includes('第二条测试发现')")
                assert js(f"{prefix}.desktopSelectedFinding().title === '第二条测试发现'")
                js(f"{prefix}.desktopFindingIndex=0; true")
                js(f"{prefix}.desktopFindingSection='detail'; true")
                js(f"{prefix}.desktopFindingModalOpen=false; true")
                js(f"{prefix}.openDesktopOriginalFact(); true")
                wait_for(f"{prefix}.desktopOriginalFactOpen")
                wait_for("document.getElementById('graph').contentDocument.querySelector('[aria-label=\"原始事实\"]')?.offsetHeight > 300")
                js(f"{prefix}.desktopOriginalFactText = '长记录 '.repeat(3000); true")
                assert js("(() => {const p=document.getElementById('graph').contentDocument.querySelector('[aria-label=\"原始事实\"]'); return p.querySelector('.overflow-y-auto').scrollHeight > p.querySelector('.overflow-y-auto').clientHeight})()")
                js(f"{prefix}.desktopOriginalFactOpen=false; true")
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
            if not args.fixture:
                wait_for(f"{prefix}.desktopFinding?.available")
                js(f"{prefix}.openDesktopFindingModal(); true")
                wait_for(f"{prefix}.desktopFindingModalOpen")
                stream = FileStream(str(FINDING_OUTPUT), FileMode.Create)
                tasks.clear()
                window.native.Invoke(Action(capture))
                try:
                    assert tasks[0].Wait(10000), "Finding result capture timed out"
                finally:
                    stream.Dispose()
                js(f"{prefix}.desktopFindingModalOpen=false; true")
                js(f"{prefix}.openDesktopOriginalFact(); true")
                wait_for(f"{prefix}.desktopOriginalFactOpen")
                stream = FileStream(str(FACT_OUTPUT), FileMode.Create)
                tasks.clear()
                window.native.Invoke(Action(capture))
                try:
                    assert tasks[0].Wait(10000), "Original fact capture timed out"
                finally:
                    stream.Dispose()
                js(f"{prefix}.desktopOriginalFactOpen=false; true")
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
            if args.fixture:
                window.native.BeginInvoke(Action(lambda: window.native.Close()))
                wait_for("!document.getElementById('shutdown-overlay').classList.contains('hidden')")
                assert window.native.TopMost and window.native.Visible
                stream = FileStream(str(CLOSE_OUTPUT), FileMode.Create)
                tasks.clear()
                window.native.Invoke(Action(capture))
                try:
                    assert tasks[0].Wait(10000), "Close dialog capture timed out"
                finally:
                    stream.Dispose()
                js("hideCloseDialog(); true")
                wait_for("document.getElementById('shutdown-overlay').classList.contains('hidden')")
                deadline = time.monotonic() + 5
                while window.native.TopMost and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert not window.native.TopMost, "Dismissed close dialog left window topmost"
                js("document.getElementById('close-behavior').value='tray'; saveCloseBehavior(); true")
                wait_for("document.getElementById('close-choice').textContent.includes('已记住：最小化到系统托盘')")
                window.native.BeginInvoke(Action(lambda: window.native.Close()))
                deadline = time.monotonic() + 5
                while window.native.Visible and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert not window.native.Visible, "Remembered tray choice did not hide the window"
                exe = Path(__file__).resolve().parent / "dist_windows" / "CairnDesktop.exe"
                if exe.is_file():
                    duplicate = subprocess.run([str(exe)], timeout=20, capture_output=True)
                    assert duplicate.returncode == 0, "Duplicate EXE did not return successfully"
                else:
                    host.restore_window()
                deadline = time.monotonic() + 5
                while not window.native.Visible and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert window.native.Visible, "Tray/single-instance restore failed"
                js("document.getElementById('close-behavior').value='ask'; saveCloseBehavior(); true")
                wait_for("document.getElementById('close-choice').textContent.includes('关闭时询问')")
                window.native.BeginInvoke(Action(lambda: window.native.Close()))
                wait_for("!document.getElementById('shutdown-overlay').classList.contains('hidden')")
                original_exit = host.exit_application
                exit_calls = []
                def count_exit():
                    exit_calls.append(True)
                    original_exit()
                host.exit_application = count_exit
                js("document.getElementById('shutdown-remember').checked=true; closeWindowAction('exit'); closeWindowAction('exit'); true")
                assert window.events.closed.wait(20), "Exit choice did not close the desktop window"
                assert len(exit_calls) == 1, f"Exit request repeated {len(exit_calls)} times"
                import json
                saved = json.loads((storage / 'data' / 'ui.json').read_text(encoding='utf-8'))
                assert saved['remember_close'] and saved['close_behavior'] == 'exit'
                print("Window close smoke passed: cancel, remembered tray, remembered exit, no Cairn service")
            print(OUTPUT)
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            if not window.events.closed.is_set():
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
