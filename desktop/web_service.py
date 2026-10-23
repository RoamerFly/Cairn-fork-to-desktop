"""Desktop operations shared by the WebView shell, without a Tk event loop."""

import json
import os
import subprocess
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

import yaml

from core import (
    CREATE_NO_WINDOW, SERVER_URL, WORKER_IMAGE, data_root, docker_available,
    load_saved_settings, make_config, output_root, runtime_root, server_available, storage_root,
)
from graph_data import project_folder, read_runs


class DesktopService:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy = False
        self.logs = deque(maxlen=2000)
        self.error = ""
        self.docker = (False, "正在检测")
        self.compose_running = False
        self.server_owned = False
        self.foreign_server = False
        self.cancel_requested = threading.Event()
        self.command_process = None
        self.log_revision = 0
        self.key, self.model = load_saved_settings(data_root() / "dispatch.yaml")
        settings = data_root() / "dispatch.yaml"
        saved = yaml.safe_load(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
        self.output_language = (saved or {}).get("runtime", {}).get("output_language", "zh-CN")
        self.log_path = storage_root() / "logs" / "desktop.log"
        if self.log_path.is_file():
            for line in self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
                self.logs.append(line)
        self.log(f"数据目录：{storage_root()}")

    def log(self, message):
        if self.key:
            message = message.replace(self.key, "[API KEY]")
        with self.lock:
            entry = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message.rstrip()}"
            self.logs.append(entry)
            self.log_revision += 1
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.is_file() and self.log_path.stat().st_size > 2_000_000:
                self.log_path.replace(self.log_path.with_suffix(".previous.log"))
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(entry + "\n")

    def status(self, known_log_revision=None):
        with self.lock:
            logs = list(self.logs) if known_log_revision != self.log_revision else None
            state = {"busy": self.busy, "logs": logs, "log_revision": self.log_revision,
                     "error": self.error}
        server = self.server_owned and server_available()
        return {**state, "server": server, "docker": self.docker[0],
                "compose_running": self.compose_running,
                "foreign_server": self.foreign_server,
                "docker_text": self.docker[1], "key_configured": bool(self.key),
                "model": self.model, "output_language": self.output_language,
                "storage": str(storage_root()), "mode": "docker"}

    def action(self, name, body):
        if name == "open_docker_desktop":
            desktop = self.docker_desktop_path()
            if desktop is None:
                raise RuntimeError("未找到 Docker Desktop。请先安装，再打开其 Settings → Resources → Proxies。")
            os.startfile(desktop)
            return {"accepted": True}
        if name in {"open_output", "open_storage", "open_project", "open_run"}:
            folder = storage_root() if name == "open_storage" else output_root()
            if name in {"open_project", "open_run"}:
                folder = project_folder(folder, body["project_id"])
            if name == "open_run":
                record = next((item for item in read_runs(output_root(), body["project_id"])
                               if os.path.basename(item["directory"]) == body["record_id"]), None)
                if not record:
                    raise ValueError("阶段记录不存在")
                folder = Path(record["directory"])
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
            return {"accepted": True}
        if name == "cancel":
            self.cancel_operation()
            return {"accepted": True}
        jobs = {"check": self.check, "save": lambda: self.save(body),
                "start": lambda: self.start(body), "stop": self.stop,
                "logs": lambda: self.command(self.compose("logs", "--tail", "100", "--no-color"), timeout=30)}
        if name not in jobs:
            raise ValueError("未知操作")
        with self.lock:
            if self.busy:
                raise ValueError("正在处理上一项操作")
            if name == "stop" and not self.compose_running:
                return {"accepted": False, "reason": "服务未运行"}
            self.busy, self.error = True, ""
            self.cancel_requested.clear()

        def run():
            try:
                jobs[name]()
            except Exception as exc:
                message = str(exc).replace(self.key, "[API KEY]") if self.key else str(exc)
                self.log(f"错误：{message}")
                with self.lock:
                    self.error = message
            finally:
                with self.lock:
                    self.busy = False
                    self.cancel_requested.clear()

        threading.Thread(target=run, daemon=True).start()
        return {"accepted": True}

    def check(self):
        self.docker = docker_available()
        self.compose_running = False
        self.server_owned = False
        self.foreign_server = False
        if self.docker[0]:
            try:
                result = subprocess.run(self.compose("ps", "--status", "running", "-q"),
                    cwd=runtime_root(), capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=15, creationflags=CREATE_NO_WINDOW)
                ids = result.stdout.split() if result.returncode == 0 else []
                expected = os.path.normcase(os.path.normpath(str(runtime_root().resolve())))
                for container_id in ids:
                    identity = subprocess.run(["docker", "inspect", "--format",
                        "{{json .Config.Labels}}", container_id],
                        capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
                    raw = identity.stdout.decode(errors="replace") if isinstance(identity.stdout, bytes) else identity.stdout
                    try:
                        labels = json.loads(raw) if identity.returncode == 0 else {}
                    except ValueError:
                        labels = {}
                    if not isinstance(labels, dict):
                        labels = {}
                    actual = os.path.normcase(os.path.normpath(str(labels.get("com.docker.compose.project.working_dir", ""))))
                    if actual == expected:
                        self.compose_running = True
                        if labels.get("com.docker.compose.service") == "cairn-server":
                            self.server_owned = True
                    else:
                        self.foreign_server = True
            except (OSError, subprocess.TimeoutExpired):
                self.log("无法确认 Compose 服务状态，将由启动流程重新检查。")
        if server_available() and not self.server_owned:
            self.foreign_server = True

    @staticmethod
    def docker_desktop_path():
        roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")]
        candidates = [Path(root) / "Docker" / "Docker" / "Docker Desktop.exe" for root in roots[:2] if root]
        if roots[2]:
            candidates.append(Path(roots[2]) / "Programs" / "Docker" / "Docker" / "Docker Desktop.exe")
        return next((path for path in candidates if path.is_file()), None)

    def ensure_docker(self):
        self.docker = docker_available()
        if self.docker[0]:
            return
        desktop = self.docker_desktop_path()
        if desktop is None:
            raise RuntimeError("未找到 Docker Desktop。请先安装 Docker Desktop，然后重试“构建并启动”。")
        self.log("正在启动 Docker Desktop，等待 Linux 引擎就绪…")
        os.startfile(desktop)
        deadline = time.monotonic() + 240
        next_log = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.cancel_requested.is_set():
                raise RuntimeError("用户已取消启动操作。")
            self.docker = docker_available()
            if self.docker[0]:
                self.log("Docker Desktop 已就绪。")
                return
            if time.monotonic() >= next_log:
                self.log("仍在等待 Docker Linux 引擎启动…")
                next_log = time.monotonic() + 15
            time.sleep(3)
        raise RuntimeError("Docker Desktop 已打开，但 Linux 引擎在 4 分钟内未就绪。请检查 Docker Desktop 的提示后重试。")

    def save(self, body):
        key = body.get("api_key", "").strip() or self.key
        model = body.get("model", self.model)
        language = body.get("output_language", self.output_language)
        if language not in {"auto", "zh-CN", "en"}:
            raise ValueError("请选择支持的任务输出语言。")
        template = (runtime_root() / "dispatch.deepseek-codex.example.yaml").read_text(encoding="utf-8")
        config = make_config(template, key, model)
        config = config.replace("output_language: zh-CN", f"output_language: {language}")
        data_root().mkdir(parents=True, exist_ok=True)
        staged = data_root() / "dispatch.yaml.tmp"
        staged.write_text(config, encoding="utf-8")
        staged.replace(data_root() / "dispatch.yaml")
        self.key, self.model = key, model
        self.output_language = language
        self.log("配置已保存，服务重新启动后生效。")

    @staticmethod
    def compose(*args):
        return ["docker", "compose", "-f", "compose.yaml", *args]

    def command(self, args, timeout=600):
        if self.cancel_requested.is_set():
            raise RuntimeError("用户已取消当前操作。")
        self.log("$ " + " ".join(args))
        process = subprocess.Popen(args, cwd=runtime_root(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        self.command_process = process
        if self.cancel_requested.is_set():
            self._kill_command(process)
        def read_output():
            for line in process.stdout:
                self.log(line)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._kill_command(process)
                raise RuntimeError(f"命令超过 {timeout} 秒未完成，已停止；请检查运行日志。")
            if self.cancel_requested.is_set():
                raise RuntimeError("用户已取消当前操作。")
            if code != 0:
                raise RuntimeError("命令执行失败，请查看运行日志。")
        finally:
            reader.join(timeout=3)
            self.command_process = None
            process.stdout.close()

    @staticmethod
    def _kill_command(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                        capture_output=True, timeout=10, creationflags=CREATE_NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                result = None
            if (result is None or result.returncode != 0) and process.poll() is None:
                process.kill()
        else:
            process.kill()

    def cancel_operation(self):
        with self.lock:
            if not self.busy or self.cancel_requested.is_set():
                return
            self.cancel_requested.set()
        process = self.command_process
        if process:
            self._kill_command(process)
        self.log("已请求取消当前操作。")

    def start(self, body):
        self.check()
        if self.server_owned and server_available():
            raise RuntimeError("Cairn 服务已运行。请使用“停止服务”后再重新启动。")
        if self.foreign_server:
            raise RuntimeError("8000 端口已有其他 Cairn 服务或旧位置的服务。请先关闭原服务。")
        if not (body.get("api_key", "").strip() or self.key):
            raise RuntimeError("请先在设置中填写 DeepSeek API Key。")
        self.save(body)
        self.ensure_docker()
        self.check()
        if self.compose_running:
            self.log("检测到部分 Compose 服务正在运行，正在重新协调并启动完整服务。")
        installed = subprocess.run(["docker", "image", "inspect", WORKER_IMAGE],
                                   capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        if installed.returncode:
            self.log("下载 Worker 工具镜像，安装后缓存复用。")
            self.command(["docker", "pull", "--platform=linux/amd64", WORKER_IMAGE])
        else:
            self.log("复用本机已安装的 Worker 镜像。")
        self.log("正在构建 Cairn 应用镜像。首次构建需从 GHCR 下载基础镜像；若下载缓慢，请在 Docker Desktop 的 Settings → Resources → Proxies 配置 Containers proxy 后重试。")
        self.command(self.compose("up", "-d", "--build", "--force-recreate"), timeout=1800)
        self.check()
        if not self.server_owned or self.foreign_server:
            raise RuntimeError("Compose 启动后未能确认此目录的 Cairn 服务，请查看运行日志。")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.cancel_requested.is_set():
                raise RuntimeError("用户已取消启动操作。")
            if server_available():
                self.log("Cairn 服务已启动并通过 API 检查。")
                return
            time.sleep(2)
        raise RuntimeError("Compose 已启动，但 Cairn API 在 60 秒内未就绪。请查看运行日志。")

    def stop(self):
        self.check()
        if not self.compose_running:
            return
        if self.foreign_server:
            raise RuntimeError("检测到其他目录的服务；为保护该服务，请在原位置停止。")
        if not self.docker[0]:
            raise RuntimeError("Docker 引擎不可用，无法确认 Cairn 服务是否已停止。")
        if server_available():
            with urllib.request.urlopen(f"{SERVER_URL}/projects", timeout=10) as response:
                projects = json.load(response)
            active = [item["id"] for item in projects if item["status"] == "active"]
            for pid in active:
                request = urllib.request.Request(f"{SERVER_URL}/projects/{pid}/status", method="PUT",
                    data=b'{"status":"stopped"}', headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=10):
                    pass
            if active:
                self.log(f"已停止 {len(active)} 个任务，等待 Worker 清理。")
                time.sleep(5)
        self.command(self.compose("stop"), timeout=90)
        deadline = time.monotonic() + 20
        while server_available() and time.monotonic() < deadline:
            time.sleep(1)
        self.check()
        if self.compose_running or self.server_owned:
            raise RuntimeError("Compose 停止后仍检测到本目录服务，请查看运行日志。")
        self.log("服务已停止，历史图与任务文件保留。")
