"""Native project graph with node details and phase logs."""

from __future__ import annotations

import json
import os
import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import Canvas

import customtkinter as ctk

from graph_data import (
    build_graph, layout_graph, project_folder, read_projects, read_record_text, read_runs, related_intents,
)

STATUS = {"active": "运行中", "completed": "已完成", "stopped": "已停止"}


class GraphPage(ctk.CTkFrame):
    def __init__(self, parent, *, data: Path, output: Path, colors: dict, font: str):
        super().__init__(parent, corner_radius=0, fg_color=colors["main"])
        self.colors, self.font = colors, font
        self.database = data / "cairn" / "cairn.db"
        self.output = output
        self.detail = None
        self.details = {}
        self.runs = []
        self.run_options = {}
        self.nodes, self.edges = {}, []
        self.selected = None
        self.zoom = 1.0
        self.fit_to_canvas = True
        self._fit_after = None
        self.loading = False
        self.messages = queue.Queue()
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=25, pady=(25, 15))
        self._label(header, "任务过程图", 30, True).pack(anchor="w")
        self._label(header, "事实 → 行动 → 新事实 → 目标 · 点击节点查看详情与执行记录", 14).pack(anchor="w")
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=25, pady=(0, 12))
        self.project_menu = ctk.CTkOptionMenu(toolbar, values=["暂无任务"], width=340, command=self._choose_project)
        self.project_menu.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._button(toolbar, "刷新", self.refresh, 75).pack(side="left", padx=(0, 7))
        self._button(toolbar, "－", lambda: self._zoom(0.8), 36).pack(side="left", padx=(0, 4))
        self._button(toolbar, "＋", lambda: self._zoom(1.25), 36).pack(side="left", padx=(0, 7))
        self._button(toolbar, "适应画布", self._fit, 95).pack(side="left", padx=(0, 7))
        self._button(toolbar, "打开文件", self._open_project, 95).pack(side="left")

        split = ctk.CTkFrame(self, fg_color="transparent")
        split.grid(row=2, column=0, sticky="nsew", padx=25, pady=(0, 10))
        split.grid_rowconfigure(0, weight=1)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        plot = ctk.CTkFrame(split, fg_color=colors["terminal"], corner_radius=10)
        plot.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        plot.grid_rowconfigure(0, weight=1)
        plot.grid_columnconfigure(0, weight=1)
        self.canvas = Canvas(plot, bg=colors["terminal"], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        xbar = ctk.CTkScrollbar(plot, orientation="horizontal", command=self.canvas.xview)
        xbar.grid(row=1, column=0, sticky="ew")
        ybar = ctk.CTkScrollbar(plot, command=self.canvas.yview)
        ybar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.canvas.bind("<ButtonPress-2>", lambda event: self.canvas.scan_mark(event.x, event.y))
        self.canvas.bind("<B2-Motion>", lambda event: self.canvas.scan_dragto(event.x, event.y, gain=1))
        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(-int(event.delta / 120), "units"))

        inspector = ctk.CTkFrame(split, fg_color=colors["card"], width=390)
        inspector.grid(row=0, column=1, sticky="nsew")
        inspector.grid_columnconfigure(0, weight=1)
        inspector.grid_rowconfigure(4, weight=1)
        self.node_title = self._label(inspector, "选择一个节点", 18, True)
        self.node_title.grid(row=0, column=0, sticky="w", padx=15, pady=(12, 0))
        self.summary = self._textbox(inspector, 190)
        self.summary.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 6))
        self.run_note = self._label(inspector, "下方显示项目阶段记录", 12)
        self.run_note.grid(row=2, column=0, sticky="ew", padx=12)
        self.run_menu = ctk.CTkOptionMenu(inspector, values=["暂无阶段记录"], command=self._choose_run)
        self.run_menu.grid(row=3, column=0, sticky="ew", padx=12, pady=(5, 5))
        self.tabs = ctk.CTkTabview(inspector, fg_color=colors["card_alt"], height=310)
        self.tabs.grid(row=4, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.record_boxes = {}
        for name in ("任务参数", "执行输出", "错误日志"):
            tab = self.tabs.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            box = self._textbox(tab, 200)
            box.grid(row=0, column=0, sticky="nsew")
            self.record_boxes[name] = box
        self._button(inspector, "打开阶段记录目录", self._open_record, 160).grid(row=5, column=0, sticky="w", padx=12, pady=(0, 12))
        self.status = self._label(self, "读取本地任务数据库；停止服务后仍可查看。", 12)
        self.status.grid(row=3, column=0, sticky="w", padx=25, pady=(0, 12))
        self.after(100, self._drain)
        self.after(5000, self._poll)

    def _label(self, parent, text, size, bold=False):
        return ctk.CTkLabel(parent, text=text, anchor="w", text_color=self.colors["text"],
                            font=ctk.CTkFont(family=self.font, size=size, weight="bold" if bold else "normal"))

    def _button(self, parent, text, callback, width):
        return ctk.CTkButton(parent, text=text, command=callback, width=width, height=36,
                             fg_color=self.colors["selected"], hover_color=self.colors["border"],
                             font=ctk.CTkFont(family=self.font, size=13))

    def _textbox(self, parent, height):
        box = ctk.CTkTextbox(parent, height=height, wrap="word", fg_color=self.colors["terminal"],
                             text_color=self.colors["text"], font=ctk.CTkFont(family=self.font, size=13))
        box.configure(state="disabled")
        return box

    @staticmethod
    def _text(box, text):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.project_menu.configure(state="disabled")
        selected = self.detail["project"]["id"] if self.detail else None

        def load():
            try:
                details = read_projects(self.database)
                existing = {item["project"]["id"] for item in details}
                pid = selected if selected in existing else (details[0]["project"]["id"] if details else None)
                runs = read_runs(self.output, pid) if pid else []
                self.messages.put(("refresh", details, pid, runs))
            except Exception as exc:
                self.messages.put(("error", str(exc)))

        threading.Thread(target=load, daemon=True).start()

    def _drain(self):
        try:
            while True:
                event = self.messages.get_nowait()
                self.loading = False
                self.project_menu.configure(state="normal")
                if event[0] == "error":
                    self.status.configure(text=f"读取失败：{event[1]}")
                    continue
                _, details, pid, runs = event
                self.details = {f"{item['project']['id']} · {item['project']['title']}": item for item in details}
                values = list(self.details) or ["暂无任务"]
                self.project_menu.configure(values=values)
                label = next((key for key, item in self.details.items() if item["project"]["id"] == pid), values[0])
                self.project_menu.set(label)
                self.runs = runs
                self._display(self.details.get(label), preserve=True)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _poll(self):
        if self.winfo_ismapped():
            self.refresh()
        self.after(5000, self._poll)

    def _choose_project(self, label):
        detail = self.details.get(label)
        if not detail:
            return
        # Refresh on a background thread; preserve the newly chosen project.
        self.detail = detail
        self.selected = None
        self.runs = []
        self._display(detail)
        self.refresh()

    def _display(self, detail, preserve=False):
        changed = not self.detail or not detail or self.detail["project"]["id"] != detail["project"]["id"]
        self.detail = detail
        if not detail:
            self.nodes, self.edges, self.runs, self.run_options = {}, [], [], {}
            self.selected = None
            self.canvas.delete("all")
            self.node_title.configure(text="选择一个节点")
            self._text(self.summary, "暂无任务。创建任务后，事实与行动会在这里显示。")
            self.run_menu.configure(values=["暂无阶段记录"])
            self.run_menu.set("暂无阶段记录")
            self._choose_run("暂无阶段记录")
            self.status.configure(text="尚无本地任务数据库，可先创建一个任务。")
            return
        self.nodes, self.edges = build_graph(detail)
        self._draw_graph()
        if changed or not preserve:
            self.fit_to_canvas = True
            self.after(100, self._fit)
        self._select_node(self.selected if self.selected in self.nodes else "fact:origin")
        project = detail["project"]
        self.status.configure(text=f"{STATUS.get(project['status'], project['status'])}  ·  {len(detail['facts'])} 个事实  /  {len(detail['intents'])} 个行动  ·  每 5 秒刷新  ·  只读本地记录")

    def _draw_graph(self):
        self.canvas.delete("all")
        if not self.nodes:
            return
        positions, cycle = layout_graph(self.nodes, self.edges)
        scale = self.zoom * self._get_widget_scaling()
        width, height = 245 * scale, 108 * scale
        graph_width = (max(x for x, _ in positions.values()) + 285) * scale
        offset_x = max(0, (self.canvas.winfo_width() - graph_width) / 2)
        for source, target in self.edges:
            sx, sy = positions[source]
            tx, ty = positions[target]
            self.canvas.create_line((sx + 122.5) * scale + offset_x, (sy + 108) * scale,
                                    (tx + 122.5) * scale + offset_x, ty * scale,
                                    fill=self.colors["dim"], width=max(1, 2 * scale), arrow="last", arrowshape=(8 * scale, 10 * scale, 4 * scale))
        for key, node in self.nodes.items():
            x, y = (value * scale for value in positions[key])
            x += offset_x
            if node["kind"] == "intent":
                status = "已完成" if node.get("concluded_at") else "处理中" if node.get("worker") else "待执行"
                label = f"行动 {node['id']} · {status}"
                color = "#2E3448" if not node.get("concluded_at") else "#20384B"
            else:
                label = "任务起点" if node["id"] == "origin" else "任务目标" if node["id"] == "goal" else f"事实 {node['id']}"
                color = "#183C36" if node["id"] == "goal" and self.detail["project"]["status"] == "completed" else self.colors["card"]
            tag = "node_" + key.replace(":", "_")
            outline = self.colors["accent"] if key == self.selected else self.colors["border"]
            self.canvas.create_rectangle(x, y, x + width, y + height, fill=color, outline=outline,
                                         width=max(1, 2 * scale), tags=(tag,))
            self.canvas.create_text(x + 14 * scale, y + 13 * scale, text=label, anchor="nw", fill=self.colors["accent"],
                                    font=(self.font, -max(9, int(14 * scale)), "bold"), tags=(tag,))
            description = " ".join(node.get("description", "").split())
            description = description[:45] + ("…" if len(description) > 45 else "")
            self.canvas.create_text(x + 14 * scale, y + 42 * scale, text=description, anchor="nw", width=215 * scale,
                                    fill=self.colors["text"], font=(self.font, -max(8, int(12 * scale))), tags=(tag,))
            self.canvas.tag_bind(tag, "<Button-1>", lambda event, selected=key: self._select_node(selected))
        bounds = self.canvas.bbox("all")
        if bounds:
            self.canvas.configure(scrollregion=(0, 0, bounds[2] + 40 * scale, bounds[3] + 40 * scale))
        if cycle:
            self.canvas.create_text(15, 15, anchor="nw", text="记录中包含循环依赖，布局已保留原连接", fill="#FFCE80")

    def _zoom(self, ratio):
        self.fit_to_canvas = False
        self.zoom = max(0.25, min(2.0, self.zoom * ratio))
        self._draw_graph()

    def _canvas_resized(self, event):
        if self.fit_to_canvas:
            if self._fit_after:
                self.after_cancel(self._fit_after)
            self._fit_after = self.after(100, self._fit)

    def _fit(self):
        self._fit_after = None
        self.fit_to_canvas = True
        if not self.nodes:
            return
        positions, _ = layout_graph(self.nodes, self.edges)
        w = max(x for x, _ in positions.values()) + 285
        h = max(y for _, y in positions.values()) + 150
        dpi = self._get_widget_scaling()
        self.zoom = max(0.25, min(1.0, self.canvas.winfo_width() / (w * dpi), self.canvas.winfo_height() / (h * dpi)))
        self._draw_graph()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _select_node(self, key):
        if key not in self.nodes:
            return
        self.selected = key
        node = self.nodes[key]
        self.node_title.configure(text=("行动节点 · " if node["kind"] == "intent" else "事实节点 · ") + node["id"])
        lines = [node.get("description", "")]
        if node["kind"] == "intent":
            lines.extend(("", f"输入事实：{', '.join(node.get('from', []))}", f"产出事实：{node.get('to') or '尚未产出'}",
                          f"创建者：{node.get('creator', '')}", f"Worker：{node.get('worker') or '未领取'}",
                          f"创建时间：{node.get('created_at')}", f"完成时间：{node.get('concluded_at') or '未完成'}"))
            if node.get("concluded_at"):
                try:
                    duration = (datetime.fromisoformat(node["concluded_at"]) - datetime.fromisoformat(node["created_at"])).total_seconds()
                    lines.append(f"行动总历时：{duration:.1f} 秒（包括等待）")
                except ValueError:
                    pass
        else:
            incoming = related_intents(node, self.detail)
            lines.extend(("", f"来源行动：{', '.join(sorted(incoming)) or '项目初始输入'}"))
            if node["id"] == "origin":
                lines.append(f"项目创建：{self.detail['project']['created_at']}")
                lines.extend(f"补充提示：{hint['content']}" for hint in self.detail.get("hints", []))
        self._text(self.summary, "\n".join(lines))
        ids = related_intents(node, self.detail)
        exact = [record for record in self.runs if record.get("intent_id") in ids]
        records = exact or self.runs
        self.run_note.configure(text="节点关联的执行阶段" if exact else "项目级记录（该节点暂无独立阶段关联）")
        self.run_options = {
            f"{index + 1}. {record.get('phase', '阶段')} · {record.get('worker', '')}": record
            for index, record in enumerate(records)
        }
        options = list(self.run_options) or ["暂无阶段记录"]
        previous = self.run_menu.get()
        current = previous if previous in options else options[0]
        self.run_menu.configure(values=options)
        self.run_menu.set(current)
        self._choose_run(current)
        self._draw_graph()

    def _choose_run(self, label):
        record = self.run_options.get(label)
        if not record:
            for box in self.record_boxes.values():
                self._text(box, "暂无归档。阶段结束后会保存输出；实时过程可打开 Codex 会话目录查看。")
            return
        self._text(self.record_boxes["任务参数"], json.dumps({key: value for key, value in record.items() if key != "directory"}, ensure_ascii=False, indent=2))
        self._text(self.record_boxes["执行输出"], read_record_text(record, "stdout.log"))
        self._text(self.record_boxes["错误日志"], read_record_text(record, "stderr.log"))

    def _open_project(self):
        if self.detail:
            folder = project_folder(self.output, self.detail["project"]["id"])
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)

    def _open_record(self):
        record = self.run_options.get(self.run_menu.get())
        if record:
            os.startfile(record["directory"])
