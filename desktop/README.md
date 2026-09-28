# Cairn Windows 桌面版

`CairnDesktop.exe` 是 Cairn 的单文件 Windows 图形启动器，用于配置和运行 Docker 中的 Cairn 服务及 Codex Worker。界面采用中文，设计参考见 [中文设计稿](design/cairn-desktop-mockup-cn.png)。程序内含 Cairn 源码、锁文件、Dockerfile、Compose 配置和 DeepSeek/Codex 配置模板；目标电脑无需另装 Python，但需要 Docker Desktop 运行 Linux 容器。Windows 命名互斥量保证界面只运行一个实例，重复打开会切回已打开的窗口。

首次启动时，EXE 同级会自动创建 `CairnDesktopData`：`app` 保存解压的运行文件，`data` 保存配置与 SQLite 数据库，`output/<项目 ID>/workspace` 保存 Agent 的工作文件，`output/<项目 ID>/codex` 保存 Codex 会话。DeepSeek API Key 以明文保存在 `CairnDesktopData\data\dispatch.yaml`，不会被打包进 EXE。旧版 `%LOCALAPPDATA%\CairnDesktop` 的配置和数据库会复制到新目录，旧文件保留。请把 EXE 放在可写目录；复制 EXE 时连同 `CairnDesktopData` 一起复制即可迁移状态。可用 `CAIRN_DESKTOP_STORAGE_ROOT` 覆盖存储根目录。Web 服务仅监听 `127.0.0.1:8000`。

每个 Worker 阶段结束后，原始输出和任务参数保存在 `workspace/.cairn/runs/<阶段-ID>/`；推理阶段的图快照保存在 `workspace/.cairn/prompts/`。Agent 主动生成的报告、请求记录等保存在工作目录中。运行时可从“运行日志”页点击“打开任务文件”。即使 Worker 容器被删除，挂载目录中的文件也会保留；Codex 会话文件在运行过程中持续写入。旧版未挂载目录的 Worker 文件仍在旧 Docker 容器内，需要另外导出，它们不会随数据库自动迁移。

## 构建

在 Windows 上双击 `desktop\build_windows.bat`，或从仓库根目录运行：

```powershell
desktop\build_windows.bat
```

批处理脚本会在 `desktop\build\.venv` 创建独立的 Python 构建环境，并在缺少构建依赖时安装 PyInstaller、CustomTkinter 和 Pillow。产物是 `desktop\dist_windows\CairnDesktop.exe`。Windows EXE 须在 Windows 上构建。构建脚本生成运行包后，也可以用 `python desktop/gui.py` 直接调试界面。

## 运行

1. 启动 Docker Desktop，并确保使用 Linux 容器。
2. 运行 `CairnDesktop.exe`，填写你的 DeepSeek API Key、选择模型，然后点击“构建并启动”。
3. 在“新建任务”页创建任务，或打开 `http://127.0.0.1:8000` 使用 Cairn Web 界面。
4. 使用“停止服务”停止当前任务和 Cairn 的 Compose 服务。

首次构建需要下载体积较大的 `linux/amd64` Kali Worker 镜像，并构建 Cairn 应用镜像。若靶站运行在 Windows 主机上，请在任务 URL 中使用 `host.docker.internal` 作为主机名；可从容器访问的外部 URL 可以直接填写。桌面程序不会安装或自动启动 Docker Desktop。

## 本地检查

```powershell
python -m py_compile desktop/core.py desktop/single_instance.py desktop/gui.py desktop/build.py desktop/smoke_test.py desktop/visual_smoke.py
python desktop/smoke_test.py
```

冒烟测试覆盖运行包解压、配置生成、旧数据迁移、Compose 配置和 EXE 单实例行为。界面截图可用 `python desktop/visual_smoke.py` 生成；输出截图仅用于本地检查，不提交到仓库。
