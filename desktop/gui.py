"""Chinese dark-console UI for Cairn Desktop."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from tkinter import Canvas, END, messagebox

import customtkinter as ctk

from core import (
    APP_TITLE,
    CREATE_NO_WINDOW,
    SERVER_URL,
    WORKER_IMAGE,
    bundled_payload,
    data_root,
    docker_available,
    ensure_runtime,
    load_saved_settings,
    make_config,
    migrate_legacy_storage,
    runtime_root,
    server_available,
    storage_root,
)
from single_instance import SingleInstance


COLORS = {
    "sidebar": "#0A1721",
    "main": "#101E29",
    "card": "#182A36",
    "card_alt": "#142430",
    "input": "#10212C",
    "border": "#2A4050",
    "text": "#EAF3F8",
    "muted": "#9BB0BF",
    "dim": "#6E879A",
    "accent": "#31C5EC",
    "accent_hover": "#67D6F2",
    "selected": "#12374A",
    "success": "#1ED37B",
    "offline": "#637E90",
    "terminal": "#0D1A24",
}
FONT = "Microsoft YaHei UI"
MONO = "Consolas"


class CairnDesktop(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=COLORS["main"])
        self.title(APP_TITLE)
        self.geometry(self._initial_geometry())
        self.minsize(1080, 720)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.runtime = runtime_root()
        self.data = data_root()
        self.busy = False
        self.key = ctk.StringVar()
        self.model = ctk.StringVar(value="deepseek-flash")
        self.title_var = ctk.StringVar()
        self.target_url = ctk.StringVar()
        self.bootstrap = ctk.BooleanVar(value=False)
        self._show_secret = False
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkBaseClass] = {}
        self._action_buttons: list[ctk.CTkButton] = []
        self._build_shell()
        self._build_overview()
        self._build_mission()
        self._build_activity()
        self._build_about()
        self.show_page("overview")
        self.after(100, self._drain_events)
        self._start_task(self._initialize)

    def _initial_geometry(self) -> str:
        width = min(1490, max(1080, self.winfo_screenwidth() - 90))
        height = min(970, max(720, self.winfo_screenheight() - 100))
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        return f"{width}x{height}+{x}+{y}"

    @staticmethod
    def _label(parent, text: str, size: int = 15, color: str | None = None, bold: bool = False, **kwargs):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal"),
            text_color=color or COLORS["text"],
            **kwargs,
        )

    @staticmethod
    def _card(parent, **kwargs):
        return ctk.CTkFrame(
            parent,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=13,
            **kwargs,
        )

    @staticmethod
    def _button(parent, text: str, command, primary: bool = False, width: int = 140, height: int = 46):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            corner_radius=9,
            fg_color=COLORS["accent"] if primary else COLORS["card_alt"],
            hover_color=COLORS["accent_hover"] if primary else "#253C4C",
            text_color=COLORS["sidebar"] if primary else COLORS["text"],
            border_width=0 if primary else 1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
        )

    def _build_shell(self) -> None:
        self.grid_columnconfigure(0, minsize=255)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=255, corner_radius=0, fg_color=COLORS["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(2, weight=1)
        brand = ctk.CTkFrame(sidebar, fg_color="transparent", height=125)
        brand.grid(row=0, column=0, sticky="ew", padx=30, pady=(24, 18))
        brand.grid_propagate(False)
        icon = Canvas(brand, width=62, height=72, bg=COLORS["sidebar"], highlightthickness=0)
        icon.place(x=0, y=2)
        icon.create_oval(17, 7, 45, 27, fill="#72BEE3", outline="")
        icon.create_oval(11, 30, 50, 49, fill="#61B8E1", outline="")
        icon.create_oval(5, 52, 57, 70, fill="#4AA9D5", outline="")
        self._label(brand, "CAIRN", size=30, bold=True).place(x=70, y=10)
        self._label(brand, "控制中心", size=12, color=COLORS["dim"]).place(x=72, y=55)

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=8)
        for page, label, glyph in (
            ("overview", "总览", "⌂"),
            ("mission", "新建任务", "+"),
            ("activity", "运行日志", "▥"),
        ):
            button = ctk.CTkButton(
                nav,
                text=f"{glyph}    {label}",
                width=239,
                height=62,
                anchor="w",
                corner_radius=9,
                fg_color="transparent",
                hover_color="#1B3949",
                text_color=COLORS["muted"],
                font=ctk.CTkFont(family=FONT, size=17),
                command=lambda target=page: self.show_page(target),
            )
            button.pack(fill="x", pady=4)
            self._nav_buttons[page] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=28, pady=22)
        ctk.CTkFrame(footer, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=(0, 15))
        ctk.CTkButton(
            footer,
            text="关于 Cairn Desktop",
            anchor="w",
            fg_color="transparent",
            hover_color="#1B3949",
            text_color=COLORS["dim"],
            font=ctk.CTkFont(family=FONT, size=12),
            command=lambda: self.show_page("about"),
        ).pack(fill="x", pady=(0, 5))
        ctk.CTkButton(
            footer,
            text="●  本地工作区    ›",
            anchor="w",
            fg_color="transparent",
            hover_color="#1B3949",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(family=FONT, size=13),
            command=self.open_runtime,
        ).pack(fill="x")

        self.content = ctk.CTkFrame(self, fg_color=COLORS["main"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _new_page(self, name: str):
        page = ctk.CTkScrollableFrame(
            self.content,
            fg_color=COLORS["main"],
            corner_radius=0,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["dim"],
        )
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        self._pages[name] = page
        return page

    def show_page(self, name: str) -> None:
        for key, page in self._pages.items():
            if key == name:
                page.grid()
            else:
                page.grid_remove()
        for key, button in self._nav_buttons.items():
            selected = key == name
            button.configure(
                fg_color=COLORS["selected"] if selected else "transparent",
                text_color=COLORS["accent"] if selected else COLORS["muted"],
            )

    def _page_header(self, page, title: str, subtitle: str, action: tuple[str, object] | None = None):
        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", padx=25, pady=(23, 24))
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        self._label(left, title, size=34, bold=True).pack(anchor="w")
        self._label(left, subtitle, size=15, color=COLORS["muted"]).pack(anchor="w", pady=(1, 0))
        if action:
            self._button(header, action[0], action[1], width=185, height=47).pack(side="right", pady=5)

    def _build_overview(self) -> None:
        page = self._new_page("overview")
        self._page_header(page, "总览", "探索环境，一目了然", ("↗  打开网页控制台", self.open_web))

        statuses = ctk.CTkFrame(page, fg_color="transparent")
        statuses.pack(fill="x", padx=25, pady=(0, 18))
        statuses.grid_columnconfigure((0, 1), weight=1, uniform="status")
        docker_card = self._card(statuses, height=110)
        docker_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        docker_card.grid_propagate(False)
        server_card = self._card(statuses, height=110)
        server_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        server_card.grid_propagate(False)
        self._label(docker_card, "▦", size=39, color=COLORS["accent"]).place(x=30, y=28)
        self._label(docker_card, "DOCKER 引擎", size=14, color=COLORS["muted"], bold=True).place(x=110, y=20)
        self.docker_state = self._label(docker_card, "●  检查中", size=18, bold=True)
        self.docker_state.place(x=110, y=53)
        self._label(server_card, "▤", size=39, color=COLORS["dim"]).place(x=30, y=28)
        self._label(server_card, "CAIRN 服务", size=14, color=COLORS["muted"], bold=True).place(x=110, y=20)
        self.server_state = self._label(server_card, "●  检查中", size=18, bold=True)
        self.server_state.place(x=110, y=53)

        middle = ctk.CTkFrame(page, fg_color="transparent")
        middle.pack(fill="x", padx=25, pady=(0, 18))
        middle.grid_columnconfigure(0, weight=2, uniform="middle")
        middle.grid_columnconfigure(1, weight=1, uniform="middle")
        model_card = self._card(middle, height=277)
        model_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        model_card.grid_propagate(False)
        model_card.grid_columnconfigure(0, weight=1)
        self._label(model_card, "模型连接", size=24, bold=True).grid(row=0, column=0, sticky="w", padx=23, pady=(17, 10))
        self._label(model_card, "模型", size=15, color=COLORS["muted"]).grid(row=1, column=0, sticky="w", padx=23)
        model_menu = ctk.CTkOptionMenu(
            model_card,
            variable=self.model,
            values=["deepseek-flash", "deepseek-v4-pro"],
            height=43,
            corner_radius=8,
            fg_color=COLORS["input"],
            button_color=COLORS["input"],
            button_hover_color=COLORS["selected"],
            dropdown_fg_color=COLORS["card"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=FONT, size=15),
        )
        model_menu.grid(row=2, column=0, sticky="ew", padx=23, pady=(5, 13))
        self._label(model_card, "API 密钥", size=15, color=COLORS["muted"]).grid(row=3, column=0, sticky="w", padx=23)
        key_row = ctk.CTkFrame(model_card, fg_color="transparent")
        key_row.grid(row=4, column=0, sticky="ew", padx=23, pady=(5, 0))
        key_row.grid_columnconfigure(0, weight=1)
        self.key_entry = ctk.CTkEntry(
            key_row,
            textvariable=self.key,
            show="●",
            height=45,
            corner_radius=8,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family=MONO, size=15),
        )
        self.key_entry.grid(row=0, column=0, sticky="ew")
        self._button(key_row, "显示", self.toggle_secret, width=55, height=45).grid(row=0, column=1, padx=(8, 0))
        save = self._button(key_row, "保存", self.save_config, primary=True, width=85, height=45)
        save.grid(row=0, column=2, padx=(8, 0))
        self._action_buttons.append(save)
        self._label(model_card, "密钥仅保存在本机用户目录", size=12, color=COLORS["muted"]).grid(
            row=5, column=0, sticky="w", padx=23, pady=(7, 0)
        )

        guide = self._card(middle, height=277)
        guide.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        guide.grid_propagate(False)
        self._label(guide, "快速开始", size=24, bold=True).pack(anchor="w", padx=22, pady=(17, 12))
        for index, instruction in enumerate(("配置 DeepSeek 模型连接", "构建并启动服务", "打开网页控制台开始探索"), 1):
            step = ctk.CTkFrame(guide, fg_color="transparent")
            step.pack(fill="x", padx=22, pady=5)
            self._label(
                step, str(index), size=15, bold=True, width=36, height=36, fg_color=COLORS["card_alt"], corner_radius=18
            ).pack(side="left")
            self._label(step, instruction, size=14, color=COLORS["muted"], wraplength=250).pack(
                side="left", padx=13, fill="x", expand=True, anchor="w"
            )

        actions = self._card(page, height=92)
        actions.pack(fill="x", padx=25, pady=(0, 18))
        actions.pack_propagate(False)
        row = ctk.CTkFrame(actions, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=15, pady=14)
        start = self._button(row, "▶  构建并启动", self.start_cairn, primary=True, width=190, height=57)
        start.pack(side="left", padx=(0, 12))
        stop = self._button(row, "■  停止服务", self.stop_cairn, width=150, height=57)
        stop.pack(side="left", padx=(0, 10))
        self._action_buttons.extend((start, stop))
        ctk.CTkButton(
            row,
            text="⟳  检查环境",
            command=self.refresh_status,
            width=128,
            height=57,
            fg_color="transparent",
            hover_color=COLORS["selected"],
            text_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT, size=14),
        ).pack(side="left")
        self._label(row, "访问地址：127.0.0.1:8000", size=12, color=COLORS["muted"]).pack(side="right", padx=4)

        recent = self._card(page)
        recent.pack(fill="both", expand=True, padx=25, pady=(0, 23))
        recent_header = ctk.CTkFrame(recent, fg_color="transparent")
        recent_header.pack(fill="x", padx=19, pady=(14, 8))
        self._label(recent_header, "最近活动", size=23, bold=True).pack(side="left")
        ctk.CTkButton(
            recent_header,
            text="⟳  刷新日志",
            command=self.refresh_logs,
            fg_color="transparent",
            hover_color=COLORS["selected"],
            text_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT, size=13),
            width=105,
        ).pack(side="right")
        self.recent_log = self._new_log_box(recent, height=185)
        self.recent_log.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def _build_mission(self) -> None:
        page = self._new_page("mission")
        self._page_header(page, "新建任务", "指定起点与目标，Cairn 会自动规划探索路径")
        card = self._card(page)
        card.pack(fill="x", padx=25, pady=(0, 18))
        card.grid_columnconfigure(0, weight=1)
        self._label(card, "任务信息", size=24, bold=True).grid(row=0, column=0, sticky="w", padx=25, pady=(20, 17))
        for label, variable, row in (
            ("任务标题", self.title_var, 1),
            ("测试 URL", self.target_url, 3),
        ):
            self._label(card, label, size=15, color=COLORS["muted"]).grid(row=row, column=0, sticky="w", padx=25)
            ctk.CTkEntry(
                card, textvariable=variable, height=47, corner_radius=8, fg_color=COLORS["input"],
                border_color=COLORS["border"], text_color=COLORS["text"], font=ctk.CTkFont(family=FONT, size=15),
            ).grid(row=row + 1, column=0, sticky="ew", padx=25, pady=(5, 17))
        self._label(card, "完成目标", size=15, color=COLORS["muted"]).grid(row=5, column=0, sticky="w", padx=25)
        self.goal_text = self._new_input_box(card, height=105)
        self.goal_text.grid(row=6, column=0, sticky="ew", padx=25, pady=(5, 17))
        self._label(card, "补充提示与范围", size=15, color=COLORS["muted"]).grid(row=7, column=0, sticky="w", padx=25)
        self.hint_text = self._new_input_box(card, height=105)
        self.hint_text.grid(row=8, column=0, sticky="ew", padx=25, pady=(5, 10))
        ctk.CTkCheckBox(
            card, text="先进行快速尝试", variable=self.bootstrap,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["muted"], font=ctk.CTkFont(family=FONT, size=14),
        ).grid(row=9, column=0, sticky="w", padx=25, pady=(5, 18))
        submit = self._button(card, "＋  创建并开始", self.create_project, primary=True, width=185, height=49)
        submit.grid(row=10, column=0, sticky="w", padx=25, pady=(0, 24))
        self._action_buttons.append(submit)
        self._label(
            page,
            "提示：如果目标服务运行在 Windows 本机，请使用 host.docker.internal 作为容器可访问的主机名。",
            size=13,
            color=COLORS["muted"],
            wraplength=850,
        ).pack(anchor="w", padx=26)

    def _build_activity(self) -> None:
        page = self._new_page("activity")
        self._page_header(page, "运行日志", "查看服务状态与调度器输出", ("⟳  刷新日志", self.refresh_logs))
        card = self._card(page)
        card.pack(fill="both", expand=True, padx=25, pady=(0, 18))
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(16, 10))
        self._label(header, "Cairn · 实时记录", size=22, bold=True).pack(side="left")
        self._label(header, "最多保留最近 2000 行", size=12, color=COLORS["dim"]).pack(side="right")
        self.full_log = self._new_log_box(card, height=520)
        self.full_log.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._button(page, "打开数据目录", self.open_runtime, width=150).pack(anchor="w", padx=25, pady=(0, 20))

    def _build_about(self) -> None:
        page = self._new_page("about")
        self._page_header(page, "关于", "Cairn Desktop · 桌面运行控制台")
        card = self._card(page)
        card.pack(fill="x", padx=25)
        details = (
            ("应用版本", "0.2.0"),
            ("Cairn 核心", "0.2.1"),
            ("开发者", "RoamerFly"),
            ("运行方式", "Codex Worker · DeepSeek API · Docker Desktop"),
            ("数据目录", str(storage_root())),
        )
        for index, (label, value) in enumerate(details):
            line = ctk.CTkFrame(card, fg_color="transparent")
            line.pack(fill="x", padx=25, pady=(19 if index == 0 else 8, 8 if index < len(details) - 1 else 16))
            self._label(line, label, size=14, color=COLORS["muted"], width=110, anchor="w").pack(side="left")
            self._label(line, value, size=14, wraplength=660, anchor="w").pack(side="left", fill="x", expand=True)
        links = ctk.CTkFrame(card, fg_color="transparent")
        links.pack(fill="x", padx=25, pady=(0, 25))
        self._button(links, "项目仓库 ↗", lambda: webbrowser.open("https://github.com/RoamerFly/Cairn-fork-to-desktop"), width=155).pack(side="left", padx=(0, 10))
        self._button(links, "问题反馈 ↗", lambda: webbrowser.open("https://github.com/RoamerFly/Cairn-fork-to-desktop/issues"), width=155).pack(side="left", padx=(0, 10))
        self._button(links, "开发者主页 ↗", lambda: webbrowser.open("https://github.com/RoamerFly"), width=155).pack(side="left")

    @staticmethod
    def _new_log_box(parent, height: int):
        box = ctk.CTkTextbox(
            parent, height=height, fg_color=COLORS["terminal"],
            border_color=COLORS["border"], border_width=1, corner_radius=9,
            text_color="#B4C6D3", font=ctk.CTkFont(family=MONO, size=13), wrap="word",
        )
        box.configure(state="disabled")
        return box

    @staticmethod
    def _new_input_box(parent, height: int):
        return ctk.CTkTextbox(
            parent, height=height, fg_color=COLORS["input"],
            border_color=COLORS["border"], border_width=1, corner_radius=8,
            text_color=COLORS["text"], font=ctk.CTkFont(family=FONT, size=15), wrap="word",
        )

    def toggle_secret(self) -> None:
        self._show_secret = not self._show_secret
        self.key_entry.configure(show="" if self._show_secret else "●")

    def _emit(self, kind: str, value: object) -> None:
        self.events.put((kind, value))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(str(value))
            elif kind == "status":
                docker_ok, docker_text, cairn_ok = value
                self.docker_state.configure(
                    text=f"●  {docker_text}",
                    text_color=COLORS["success"] if docker_ok else COLORS["offline"],
                )
                self.server_state.configure(
                    text="●  运行中" if cairn_ok else "●  未运行",
                    text_color=COLORS["success"] if cairn_ok else COLORS["offline"],
                )
            elif kind == "ready":
                key, model = value
                self.key.set(key)
                self.model.set(model)
            elif kind == "busy":
                self.busy = bool(value)
                for button in self._action_buttons:
                    button.configure(state="disabled" if self.busy else "normal")
            elif kind == "error":
                messagebox.showerror("Cairn Desktop", str(value))
            elif kind == "info":
                messagebox.showinfo("Cairn Desktop", str(value))
        self.after(100, self._drain_events)

    def _append_log(self, message: str) -> None:
        secret = self.key.get().strip()
        if secret:
            message = message.replace(secret, "[API KEY]")
        stamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{stamp}]  {message.rstrip()}\n"
        for box in (self.recent_log, self.full_log):
            box.configure(state="normal")
            box.insert(END, formatted)
            count = int(box.index("end-1c").split(".")[0])
            if count > 2000:
                box.delete("1.0", "501.0")
            box.see(END)
            box.configure(state="disabled")

    def _start_task(self, task, *args) -> None:
        if self.busy:
            return
        self.busy = True
        self._emit("busy", True)

        def runner() -> None:
            try:
                task(*args)
            except Exception as exc:
                self._emit("log", f"错误：{exc}")
                self._emit("error", str(exc))
            finally:
                self._emit("busy", False)

        threading.Thread(target=runner, daemon=True).start()

    def _initialize(self) -> None:
        migrate_legacy_storage(storage_root())
        ensure_runtime(bundled_payload(), self.runtime)
        self.data.mkdir(parents=True, exist_ok=True)
        self._emit("ready", load_saved_settings(self.data / "dispatch.yaml"))
        self._emit("log", f"本地工作区：{storage_root()}")
        self._check_status()

    def _check_status(self) -> bool:
        docker_ok, docker_text = docker_available()
        cairn_ok = server_available()
        self._emit("status", (docker_ok, docker_text, cairn_ok))
        return docker_ok

    def refresh_status(self) -> None:
        self._start_task(self._check_status)

    def _write_config(self, api_key: str, model: str) -> None:
        template = (self.runtime / "dispatch.deepseek-codex.example.yaml").read_text(encoding="utf-8")
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "dispatch.yaml").write_text(make_config(template, api_key, model), encoding="utf-8")

    def save_config(self) -> None:
        self._start_task(self._save_config, self.key.get(), self.model.get())

    def _save_config(self, api_key: str, model: str) -> None:
        self._write_config(api_key, model)
        self._emit("log", "模型配置已保存；已运行的调度器重启后生效。")
        self._emit("info", "模型配置已保存。")

    @staticmethod
    def _compose(*args: str) -> list[str]:
        return ["docker", "compose", "-f", "compose.yaml", *args]

    def _run_command(self, args: list[str]) -> None:
        self._emit("log", "$ " + " ".join(args))
        process = subprocess.Popen(
            args, cwd=self.runtime, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._emit("log", line)
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"命令退出码 {code}。请查看运行日志。")

    def start_cairn(self) -> None:
        self._start_task(self._start_cairn, self.key.get(), self.model.get())

    def _start_cairn(self, api_key: str, model: str) -> None:
        self._write_config(api_key, model)
        if not self._check_status():
            raise RuntimeError("Docker Linux 引擎尚未就绪，请先启动 Docker Desktop。")
        self._run_command(["docker", "pull", "--platform=linux/amd64", WORKER_IMAGE])
        self._run_command(self._compose("up", "-d", "--build", "--force-recreate"))
        self._emit("log", "Cairn 已启动。可打开网页控制台或创建任务。")
        self._check_status()

    def stop_cairn(self) -> None:
        self._start_task(self._stop_cairn)

    def _stop_cairn(self) -> None:
        if not self._check_status():
            raise RuntimeError("Docker Linux 引擎尚未就绪。")
        if server_available():
            with urllib.request.urlopen(f"{SERVER_URL}/projects", timeout=10) as response:
                projects = json.load(response)
            active_ids = [item["id"] for item in projects if item.get("status") == "active"]
            for project_id in active_ids:
                request = urllib.request.Request(
                    f"{SERVER_URL}/projects/{project_id}/status",
                    data=b'{"status":"stopped"}',
                    headers={"Content-Type": "application/json"},
                    method="PUT",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
            if active_ids:
                self._emit("log", f"已停止 {len(active_ids)} 个活跃任务，等待 Worker 清理。")
                time.sleep(5)
        self._run_command(self._compose("stop"))
        self._check_status()

    def refresh_logs(self) -> None:
        self._start_task(self._refresh_logs)

    def _refresh_logs(self) -> None:
        if not self._check_status():
            raise RuntimeError("Docker Linux 引擎尚未就绪。")
        self._run_command(self._compose("logs", "--tail", "100", "--no-color"))

    @staticmethod
    def open_web() -> None:
        webbrowser.open(SERVER_URL)

    def open_runtime(self) -> None:
        storage_root().mkdir(parents=True, exist_ok=True)
        os.startfile(storage_root())

    def create_project(self) -> None:
        title = self.title_var.get().strip()
        url = self.target_url.get().strip()
        goal = self.goal_text.get("1.0", END).strip()
        hint = self.hint_text.get("1.0", END).strip()
        if not title or not url or not goal:
            messagebox.showerror("Cairn Desktop", "请填写任务标题、测试 URL 和完成目标。")
            return
        if not url.startswith(("http://", "https://")):
            messagebox.showerror("Cairn Desktop", "测试 URL 必须以 http:// 或 https:// 开头。")
            return
        self._start_task(self._create_project, title, url, goal, hint, self.bootstrap.get())

    def _create_project(self, title: str, url: str, goal: str, hint: str, bootstrap: bool) -> None:
        if not server_available():
            raise RuntimeError("Cairn 服务未运行，请先构建并启动。")
        body: dict[str, object] = {
            "title": title,
            "origin": f"测试目标：{url}",
            "goal": goal,
            "bootstrap_enabled": bootstrap,
        }
        if hint:
            body["hints"] = [{"content": hint, "creator": "desktop-user"}]
        request = urllib.request.Request(
            f"{SERVER_URL}/projects",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"创建任务失败：HTTP {exc.code} {exc.read().decode('utf-8', 'replace')}") from exc
        self._emit("log", f"任务已创建：{data.get('id', '')} · {title}")
        self._emit("info", f"任务已创建：{data.get('id', '')}\n调度器将自动执行。")


def main() -> None:
    ctk.set_appearance_mode("dark")
    single = SingleInstance(APP_TITLE)
    if single.already_running:
        single.focus_existing()
        single.close()
        return
    try:
        app = CairnDesktop()
        app.mainloop()
    finally:
        single.close()


if __name__ == "__main__":
    main()
