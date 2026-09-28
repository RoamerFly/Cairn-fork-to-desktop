"""Loopback-only host for the upstream graph UI and read-only offline history."""

import json
import mimetypes
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request
from contextlib import closing, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from core import SERVER_URL, data_root, output_root, runtime_root
from graph_data import read_projects, read_record_text, read_runs
from web_service import DesktopService

WEB = Path(__file__).resolve().parent / "web"
ASSETS = Path(__file__).resolve().parent / "assets"


def normalize(detail):
    project = detail["project"].copy()
    project["bootstrap_enabled"] = bool(project.get("bootstrap_enabled", True))
    project["reason"] = ({"worker": project["reason_worker"], "trigger": project.get("reason_trigger"),
                          "started_at": project.get("reason_started_at"),
                          "last_heartbeat_at": project.get("reason_last_heartbeat_at")}
                         if project.get("reason_worker") else None)
    return {**detail, "project": project}


class DesktopHost:
    def __init__(self, service=None):
        self.service = service or DesktopService()
        self.token = secrets.token_urlsafe(32)
        self.static = runtime_root() / "cairn" / "src" / "cairn" / "server" / "static"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, content, mime="application/json; charset=utf-8"):
                body = content if isinstance(content, bytes) else (
                    json.dumps(content, ensure_ascii=False).encode() if mime.startswith("application/json")
                    else content.encode())
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "same-origin")
                self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                with suppress(BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    self.end_headers()
                    self.wfile.write(body)

            def dispatch(self):
                if self.headers.get("Host") != f"127.0.0.1:{owner.server.server_port}":
                    return self.reply(403, {"detail": "Invalid host"})
                try:
                    if self.command != "GET" and not secrets.compare_digest(
                            self.headers.get("X-Cairn-Token", ""), owner.token):
                        return self.reply(403, {"detail": "Invalid desktop token"})
                    parsed = urlsplit(self.path)
                    path = unquote(parsed.path)
                    length = int(self.headers.get("Content-Length", 0))
                    if length > 1_000_000 or length < 0:
                        return self.reply(413, {"detail": "Request too large"})
                    body = self.rfile.read(length) if length else b""
                    if path == "/" and self.command == "GET":
                        page = (WEB / "shell.html").read_text(encoding="utf-8").replace("__TOKEN__", owner.token)
                        return self.reply(200, page, "text/html; charset=utf-8")
                    if path == "/graph" and self.command == "GET":
                        page = (owner.static / "index.html").read_text(encoding="utf-8")
                        page = page.replace('<html lang="en">', '<html lang="zh-CN">')
                        page = page.replace('x-text="project.project.status"', 'x-text="({active:\'运行中\',stopped:\'已停止\',completed:\'已完成\'})[project.project.status]"')
                        page = page.replace('${project.facts.length} facts', '${project.facts.length} 个事实')
                        page = page.replace('${project.intents.length} intents', '${project.intents.length} 个行动')
                        page = page.replace("'Stopping...' : 'Stop Active'", "'正在停止…' : '停止运行中的任务'")
                        page = page.replace('>Log</button>', '>Log</button><button @click="sideTab = \'records\'; loadDesktopRecords()" class="flex-1 px-3 py-2.5 text-xs font-medium transition" :class="sideTab === \'records\' ? \'text-brand-600 border-b-2 border-brand-500\' : \'text-slate-400\'">执行记录</button>')
                        page = page.replace('<!-- Detail -->', (WEB / "records.html").read_text(encoding="utf-8") + '<!-- Detail -->')
                        page = page.replace('</body>', f'<script>window.DESKTOP_TOKEN={json.dumps(owner.token)}</script><script src="/desktop-assets/graph.js"></script></body>')
                        return self.reply(200, page, "text/html; charset=utf-8")
                    if path.startswith(("/static/", "/desktop-assets/", "/desktop-icons/")):
                        base = owner.static if path.startswith("/static/") else ASSETS if path.startswith("/desktop-icons/") else WEB
                        file = (base / path.split("/", 2)[2]).resolve()
                        if not file.is_relative_to(base.resolve()) or not file.is_file():
                            return self.reply(404, {"detail": "File not found"})
                        return self.reply(200, file.read_bytes(), mimetypes.guess_type(file)[0] or "application/octet-stream")
                    if path == "/desktop/status":
                        return self.reply(200, owner.service.status())
                    if path == "/desktop/preferences":
                        preferences = data_root() / "ui.json"
                        if self.command == "GET":
                            defaults = {"layout_mode": "klay_tb", "actor_name": "用户",
                                        "sidePanelWidth": 390, "remember_close": False,
                                        "close_behavior": "ask"}
                            saved = json.loads(preferences.read_text(encoding="utf-8")) if preferences.is_file() else {}
                            return self.reply(200, {**defaults, **saved})
                        if self.command == "PUT":
                            request = json.loads(body)
                            mode = request.get("layout_mode", "klay_tb")
                            if mode not in {"klay_tb", "klay_lr", "dagre_tb", "dagre_lr", "elk_tb", "elk_lr"}:
                                raise ValueError("无效布局")
                            prefs = {"layout_mode": mode, "actor_name": str(request.get("actor_name", "Human"))[:100],
                                     "sidePanelWidth": max(260, min(1500, int(request.get("sidePanelWidth", 390)))),
                                     "remember_close": bool(request.get("remember_close", False)),
                                     "close_behavior": request.get("close_behavior", "ask")}
                            if prefs["close_behavior"] not in {"ask", "exit", "tray"}:
                                raise ValueError("无效的窗口关闭选项")
                            if not prefs["remember_close"]:
                                prefs["close_behavior"] = "ask"
                            data_root().mkdir(parents=True, exist_ok=True)
                            staged = preferences.with_suffix(".tmp")
                            staged.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
                            staged.replace(preferences)
                            return self.reply(200, prefs)
                    if path == "/desktop/window" and self.command == "POST":
                        request = json.loads(body)
                        if request.get("action") == "tray" and owner.minimize_to_tray:
                            owner.minimize_to_tray()
                        elif request.get("action") == "exit" and owner.exit_application:
                            owner.exit_application()
                        else:
                            return self.reply(400, {"detail": "未知窗口操作"})
                        return self.reply(200, {"accepted": True})
                    if path == "/desktop/action" and self.command == "POST":
                        request = json.loads(body)
                        return self.reply(200, owner.service.action(request.pop("action"), request))
                    parts = path.strip("/").split("/")
                    if len(parts) >= 4 and parts[:2] == ["desktop", "projects"] and parts[3] == "runs":
                        records = read_runs(output_root(), parts[2])
                        if len(parts) == 5:
                            record = next((r for r in records if Path(r["directory"]).name == parts[4]), None)
                            if not record:
                                return self.reply(404, {"detail": "阶段不存在"})
                            return self.reply(200, {"stdout": read_record_text(record, "stdout.log"),
                                                    "stderr": read_record_text(record, "stderr.log")})
                        intent = parse_qs(parsed.query).get("intent_id", [""])[0]
                        exact = [r for r in records if intent and r.get("intent_id") == intent]
                        return self.reply(200, {"node_linked": bool(exact), "records": [
                            {**{k: v for k, v in r.items() if k != "directory"}, "record_id": Path(r["directory"]).name}
                            for r in (exact or records)]})
                    if path == "/projects" and self.command == "GET":
                        return self.reply(200, owner.summaries())
                    if path == "/settings" and self.command == "GET":
                        return self.reply(200, owner.settings())
                    if len(parts) == 2 and parts[0] == "projects" and self.command == "GET":
                        return self.reply(200, owner.detail(parts[1]))
                    if len(parts) == 3 and parts[0] == "projects" and parts[2] == "export" and self.command == "GET":
                        detail = owner.detail(parts[1])
                        export_format = parse_qs(parsed.query).get("format", ["yaml"])[0]
                        if export_format == "yaml":
                            facts = {f["id"]: f["description"] for f in detail["facts"]}
                            snapshot = {"project": {"title": detail["project"]["title"], "origin": facts.get("origin", ""),
                                        "goal": facts.get("goal", ""), "bootstrap_enabled": detail["project"]["bootstrap_enabled"]},
                                        "facts": detail["facts"], "intents": detail["intents"], "hints": detail["hints"]}
                            return self.reply(200, yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False), "text/plain; charset=utf-8")
                        if export_format == "timeline":
                            return self.reply(200, owner.timeline(detail), "text/plain; charset=utf-8")
                    if parts[0] not in {"projects", "settings"}:
                        return self.reply(404, {"detail": "Unknown route"})
                    request = urllib.request.Request(SERVER_URL + self.path, method=self.command,
                        data=body or None, headers={"Content-Type": "application/json"})
                    try:
                        with urllib.request.urlopen(request, timeout=15) as response:
                            return self.reply(response.status, response.read(), response.headers.get("Content-Type", "application/json"))
                    except urllib.error.HTTPError as exc:
                        return self.reply(exc.code, exc.read())
                    except urllib.error.URLError:
                        return self.reply(503, {"detail": "Cairn 服务未启动。历史记录可查看；请在控制中心启动服务后操作。"})
                except KeyError:
                    self.reply(404, {"detail": "记录不存在"})
                except (ValueError, OSError, sqlite3.Error) as exc:
                    self.reply(400, {"detail": str(exc)})

            do_GET = dispatch
            do_POST = dispatch
            do_PUT = dispatch
            do_DELETE = dispatch

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.minimize_to_tray = None
        self.exit_application = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def detail(self, pid):
        details = read_projects(data_root() / "cairn" / "cairn.db", pid)
        if not details:
            raise KeyError(pid)
        return normalize(details[0])

    def summaries(self):
        return [{**normalize(d)["project"], "fact_count": len(d["facts"]),
                 "intent_count": len(d["intents"]), "hint_count": len(d["hints"]),
                 "working_intent_count": sum(bool(i.get("worker")) and not i.get("to") for i in d["intents"]),
                 "unclaimed_intent_count": sum(not i.get("worker") and not i.get("to") for i in d["intents"])}
                for d in read_projects(data_root() / "cairn" / "cairn.db")]

    def settings(self):
        database = data_root() / "cairn" / "cairn.db"
        if not database.is_file():
            return {"intent_timeout": 15, "reason_timeout": 15}
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            try:
                return dict(conn.execute("SELECT intent_timeout, reason_timeout FROM settings LIMIT 1").fetchone())
            except sqlite3.Error:
                return {"intent_timeout": 15, "reason_timeout": 15}

    @staticmethod
    def timeline(detail):
        rows = [(detail["project"]["created_at"], "创建项目")]
        rows += [(i["created_at"], f"行动 {i['id']}：{i['description']}") for i in detail["intents"]]
        rows += [(i["concluded_at"], f"完成行动 {i['id']} → {i.get('to')}")
                 for i in detail["intents"] if i.get("concluded_at")]
        rows += [(h["created_at"], f"提示：{h['content']}") for h in detail["hints"]]
        return "\n\n".join(f"{stamp}  {description}" for stamp, description in sorted(rows))
