"""Exercise offline graph interactions with synthetic data, without an Agent/API."""

import json
import shutil
import time

import customtkinter as ctk

from graph_view import GraphPage
from gui import COLORS, FONT
from test_graph_data import GraphDataTests


def main():
    fixture = GraphDataTests()
    fixture.setUp()
    root = None
    try:
        data = fixture.root / "data"
        (data / "cairn").mkdir(parents=True)
        shutil.copyfile(fixture.db, data / "cairn" / "cairn.db")
        output = fixture.root / "output"
        stage = output / "p1" / "workspace" / ".cairn" / "runs" / "explore-1"
        stage.mkdir(parents=True)
        (stage / "task.json").write_text(json.dumps({
            "intent_id": "i2", "phase": "explore", "worker": "fixture",
            "duration_ms": 1250, "returncode": 0,
        }), encoding="utf-8")
        (stage / "stdout.log").write_text("synthetic process output", encoding="utf-8")
        (stage / "stderr.log").write_text("", encoding="utf-8")
        ctk.set_appearance_mode("dark")
        root = ctk.CTk()
        root.title("Cairn graph interaction test")
        root.geometry("1200x850")
        page = GraphPage(root, data=data, output=output, colors=COLORS, font=FONT)
        page.pack(fill="both", expand=True)

        def refresh_and_wait():
            page.refresh()
            deadline = time.monotonic() + 8
            while page.loading and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            root.update()
            assert not page.loading, "Graph loading timed out"

        refresh_and_wait()
        assert len(page.nodes) == 7 and len(page.edges) == 7
        bounds = page.canvas.bbox("node_intent_i2")
        x = (bounds[0] + bounds[2]) / 2 - page.canvas.canvasx(0)
        y = (bounds[1] + bounds[3]) / 2 - page.canvas.canvasy(0)
        page.canvas.event_generate("<Motion>", x=int(x), y=int(y))
        page.canvas.event_generate("<Button-1>", x=int(x), y=int(y))
        root.update()
        assert page.selected == "intent:i2", "Node click did not select the action"
        assert "输入事实：origin" in page.summary.get("1.0", "end")
        assert page.run_note.cget("text") == "节点关联的执行阶段"
        assert "synthetic process output" in page.record_boxes["执行输出"].get("1.0", "end")
        assert "1250" in page.record_boxes["任务参数"].get("1.0", "end")
        page._select_node("fact:f2")
        assert page.run_note.cget("text") == "节点关联的执行阶段"
        page._select_node("intent:i1")
        assert "项目级记录" in page.run_note.cget("text")
        zoom = page.zoom
        page._zoom(1.25)
        assert page.zoom > zoom
        page._fit()
        assert page.canvas.bbox("all")
        page.database = fixture.root / "missing.db"
        refresh_and_wait()
        assert not page.nodes and not page.run_options
        assert "暂无归档" in page.record_boxes["执行输出"].get("1.0", "end")
        print("Graph UI smoke passed: branch/join, click, node logs, zoom, empty history")
    finally:
        if root:
            root.destroy()
        fixture.tearDown()


if __name__ == "__main__":
    main()
