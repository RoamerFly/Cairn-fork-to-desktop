# Cairn Windows 桌面版

`CairnDesktop.exe` 是 Cairn 的单文件 Windows 图形启动器，用于配置和运行 Docker 中的 Cairn 服务及 Codex Worker。界面采用中文，设计参考见 [中文设计稿](design/cairn-desktop-mockup-cn.png)。程序内含 Cairn 源码、锁文件、Dockerfile、Compose 配置和 DeepSeek/Codex 配置模板；目标电脑无需另装 Python，但需要 Docker Desktop 运行 Linux 容器。Windows 命名互斥量保证界面只运行一个实例，重复打开会切回已打开的窗口。

首次启动时，EXE 同级会自动创建 `CairnDesktopData`：`app` 保存解压的运行文件，`data` 保存配置与 SQLite 数据库，`output/<项目 ID>/workspace` 保存 Agent 的工作文件，`output/<项目 ID>/codex` 保存 Codex 会话。DeepSeek API Key 以明文保存在 `CairnDesktopData\data\dispatch.yaml`，不会被打包进 EXE。旧版 `%LOCALAPPDATA%\CairnDesktop` 的配置和数据库会复制到新目录，旧文件保留。请把 EXE 放在可写目录；复制 EXE 时连同 `CairnDesktopData` 一起复制即可迁移状态。可用 `CAIRN_DESKTOP_STORAGE_ROOT` 覆盖存储根目录。Web 服务仅监听 `127.0.0.1:8000`。

每个 Worker 阶段结束后，原始输出和任务参数保存在 `workspace/.cairn/runs/<阶段-ID>/`；推理阶段的图快照保存在 `workspace/.cairn/prompts/`。Agent 主动生成的报告、请求记录等保存在工作目录中。运行时可从“运行日志”页点击“打开任务文件”。即使 Worker 容器被删除，挂载目录中的文件也会保留；Codex 会话文件在运行过程中持续写入。旧版未挂载目录的 Worker 文件仍在旧 Docker 容器内，需要另外导出，它们不会随数据库自动迁移。

## 原理与分发依赖

Cairn 是任务图与调度框架。Server 把项目、事实（Fact）、行动（Intent）和提示存入 SQLite；Dispatcher 根据图状态选择 Worker、领取行动并执行。Bootstrap 负责初始化，Reason 根据已知事实规划下一步，Explore 执行行动并把结论写回为新事实。任务可以分支、并行和汇合，直到项目完成或停止。Codex、Claude Code、Pi 是执行适配器；当前桌面模板使用 Codex 调用 DeepSeek API。

Worker 镜像提供 Kali Linux、命令行工具、浏览器依赖、资料库，以及 Codex/Claude Code/Pi CLI。每个项目从同一个镜像启动独立容器，并挂载自己的工作目录。模型通过 API 调用，镜像没有 DeepSeek 模型权重。镜像安装体积约 15.3 GB（随版本变化），压缩下载体积不同；镜像层由 Docker 共享，不会每个项目都重新下载。

当前 EXE 是桌面界面与运行文件的分发包，仍依赖 Docker Desktop。首次使用需要下载 Worker 镜像并构建应用镜像；启动时检测到 Worker 镜像已安装会直接复用，只有缺失才拉取。可以预先导入镜像实现离线交付，但仍需 Docker，模型 API 仍需联网。

上游也提供 `runtime.execution: local`，可使用主机已配置的 Agent CLI，免下载 Kali Worker 镜像。它需要主机安装运行依赖和所需工具，并使用 CLI 自身的配置；当前桌面 UI 尚未接入此模式。面向普通用户的轻量分发应增加本地执行入口或精简工具镜像，不能把目前的 EXE 描述成完全免依赖的 Agent。

## 任务过程图（0.4.0）

侧栏“任务过程图”支持切换历史项目，展示真实的 `事实 → 行动 → 新事实` 连接、分支、汇合、待执行行动和任务目标。未产出结果的行动不会显示虚构的完成连线。可以缩放、适应画布、滚动，或按住鼠标中键拖动画布。

点击节点可查看完整说明、输入和输出事实、创建者、Worker、创建/完成时间及行动总历时；阶段下拉框可查看任务参数、标准输出、错误日志和执行耗时，并打开归档目录。新的 Bootstrap/Explore 阶段通过 `intent_id` 对应到行动节点；新事实关联其来源行动。Reason 和旧版无节点编号的记录保留为项目级阶段，并在 UI 明确标注。过程信息来自任务元数据与公开执行输出，不包含模型不可见的内部思考。

页面以只读方式读取 EXE 同级的 SQLite 数据库和阶段文件，每 5 秒刷新，不要求 Docker 或 Server 运行。阶段日志在结束后归档；运行中的 Codex 会话文件持续写入 `output/<项目 ID>/codex`。长日志在 UI 中显示前 200,000 字符，可打开文件查看全文。数据库里的起点和目标自项目创建就存在，目标节点存在不代表任务已经完成。

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
python desktop/test_graph_data.py
python desktop/graph_smoke.py
```

冒烟测试覆盖运行包解压、配置生成、旧数据迁移、Compose 配置和 EXE 单实例行为。图测试覆盖只读查询、分支汇合、未完成目标、循环数据、节点日志关联与界面交互。界面截图可用 `python desktop/visual_smoke.py` 生成；过程图截图使用 `python desktop/visual_smoke.py --graph --storage desktop/dist_windows/CairnDesktopData`，只读取已有项目，不运行新任务。输出截图仅用于本地检查，不提交到仓库。
