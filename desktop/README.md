# Cairn Windows 桌面版

`CairnDesktop.exe` 0.7.0 是 Cairn 的单文件 Windows 桌面控制台，用于配置和运行 Docker 中的 Cairn 服务及 Codex Worker。图界面直接复用原项目的 HTML、Cytoscape、Dagre/Klay/ELK 布局与 Alpine 交互，通过 WebView2 放进同一个桌面窗口；控制中心与常用图操作使用中文。程序内含 Cairn 源码、锁文件、Dockerfile、Compose 配置和 DeepSeek/Codex 配置模板。目标电脑无需另装 Python，但需要 Microsoft Edge WebView2 Runtime；执行任务仍需要 Docker Desktop 运行 Linux 容器。Windows 命名互斥量保证界面只运行一个实例，重复打开会切回已打开的窗口。

首次启动时，EXE 同级会自动创建 `CairnDesktopData`：`app` 保存解压的运行文件，`data` 保存配置与 SQLite 数据库，`output/<项目 ID>/workspace` 保存 Agent 的工作文件，`output/<项目 ID>/codex` 保存 Codex 会话。DeepSeek API Key 以明文保存在 `CairnDesktopData\data\dispatch.yaml`，不会被打包进 EXE。控制中心不回传已保存密钥；输入框留空会复用本机配置。`data/ui.json` 保存图布局和面板宽度，`data/webview` 保存浏览器运行数据。旧版 `%LOCALAPPDATA%\CairnDesktop` 的配置和数据库会复制到新目录，旧文件保留。请把 EXE 放在可写目录；复制 EXE 时连同 `CairnDesktopData` 一起复制即可迁移状态。可用 `CAIRN_DESKTOP_STORAGE_ROOT` 覆盖存储根目录。Cairn API 服务仅监听 `127.0.0.1:8000`；桌面 UI 使用独立的随机本地端口，只绑定回环地址。

每个 Worker 阶段结束后，原始输出和任务参数保存在 `workspace/.cairn/runs/<阶段-ID>/`；推理阶段的图快照保存在 `workspace/.cairn/prompts/`。Agent 主动生成的报告、请求记录等保存在工作目录中。控制中心和节点“执行记录”页都可打开任务文件。即使 Worker 容器被删除，挂载目录中的文件也会保留；Codex 会话文件在运行过程中持续写入。旧版未挂载目录的 Worker 文件仍在旧 Docker 容器内，需要另外导出，它们不会随数据库自动迁移。

## 原理与分发依赖

Cairn 是任务图与调度框架。Server 把项目、事实（Fact）、行动（Intent）和提示存入 SQLite；Dispatcher 根据图状态选择 Worker、领取行动并执行。Bootstrap 负责初始化，Reason 根据已知事实规划下一步，Explore 执行行动并把结论写回为新事实。任务可以分支、并行和汇合，直到项目完成或停止。Codex、Claude Code、Pi 是执行适配器；当前桌面模板使用 Codex 调用 DeepSeek API。

Worker 镜像提供 Kali Linux、命令行工具、浏览器依赖、资料库，以及 Codex/Claude Code/Pi CLI。每个项目从同一个镜像启动独立容器，并挂载自己的工作目录。模型通过 API 调用，镜像没有 DeepSeek 模型权重。镜像安装体积约 15.3 GB（随版本变化），压缩下载体积不同；镜像层由 Docker 共享，不会每个项目都重新下载。

当前 EXE 是桌面界面与运行文件的分发包，仍依赖 Docker Desktop。首次使用需要下载 Worker 镜像并构建应用镜像；启动时检测到 Worker 镜像已安装会直接复用，只有缺失才拉取。可以预先导入镜像实现离线交付，但仍需 Docker，模型 API 仍需联网。

上游也提供 `runtime.execution: local`，可使用主机已配置的 Agent CLI，免下载 Kali Worker 镜像。它需要主机安装运行依赖和所需工具，并使用 CLI 自身的配置；当前桌面 UI 尚未接入此模式。面向普通用户的轻量分发应增加本地执行入口或精简工具镜像，不能把目前的 EXE 描述成完全免依赖的 Agent。

## 任务过程图（0.5.0）

顶部“任务过程图”打开原项目的任务列表与图。图中事实显示为节点，已完成行动显示为带说明的连线，未完成行动显示为占位节点；这是原项目的表示方式。保留真实的分支、汇合及目标连接，支持拖拽、滚轮缩放、Shift 多选、节点和连线点击、可调整宽度的详情面板、三种引擎的横/纵布局、事件时间线、过程回放及 YAML/时间线快照。默认 Klay 纵向布局。已有元素的自动刷新复用图实例，没有拓扑变化时保留用户视角。

点击事实节点或行动连线，右侧“详情”保留原项目的完整说明和来源信息；新增“执行记录”页，可查看任务参数、标准输出、错误日志、阶段耗时，并打开归档目录。新的 Bootstrap/Explore 阶段通过 `intent_id` 对应到行动；新事实关联其来源行动。Reason 和旧版无节点编号的记录保留为项目级阶段，并在 UI 明确标注。过程信息来自任务元数据与公开执行输出，不包含模型不可见的内部思考。任务说明、工具输出和记录内容不会被自动翻译。

普通事实节点的“详情”可按需点击“整理结果”，用设置中的 DeepSeek 模型把已有事实拆分为结构化的漏洞结果、证据和独立“复现”卡片。整理只读取该事实和来源行动的文字，不会向靶站发送请求；记录不足时复现步骤留空，原始事实可展开核对。结果保存在 `output/<项目 ID>/workspace/.cairn/findings/<事实 ID>.json`，事实内容变更后自动标记为过期。每次重新整理会消耗模型 Token，模型返回的用量另存为 `workspace/.cairn/runs/finding-format-*/task.json`，计入任务累计。

图、快照和归档以只读方式读取 EXE 同级的 SQLite 数据库和阶段文件，每 5 秒刷新，不要求 Docker 或 Server 运行。创建、停止、提示等操作转发到正在运行的 Cairn API；服务未启动时给出错误，不会伪造操作成功。桌面写操作需会话令牌，且拒绝非本机 Host。阶段日志在结束后归档；运行中的 Codex 会话文件持续写入 `output/<项目 ID>/codex`。长日志在 UI 中显示前 200,000 字符，可打开文件查看全文。数据库里的起点和目标自项目创建就存在，目标节点存在不代表任务已经完成。

本机模式的成本与推荐方案见 [本机执行改造方案](LOCAL_MODE_PLAN.md)。0.5.0 调整的是桌面 UI，执行端仍为 Docker。

## 设置与运行（0.7.0）

顶部“设置”页集中管理 DeepSeek 密钥、模型、任务输出语言、图布局、人工操作名称、详情面板宽度和本机存储入口。密钥留空时复用已保存配置，不回传到页面；图偏好保存后立即应用。模型与语言保存后需通过“构建并启动”重新启动服务，运行中的任务请先完成或停止。

“运行日志”区域的“复制日志”按钮可将当前日志复制到剪贴板，也支持鼠标选择后按 Ctrl+C。首次关闭窗口会弹出原生确认框，可退出并停止服务、最小化到系统托盘或继续使用；复选框可记住所选行为。设置页可以查看、更改关闭行为，托盘菜单支持恢复和退出。任务图的“执行记录”页按阶段、行动和任务累计显示 Agent CLI 报告的输入、输出与总 Token，并将原始用量写入 EXE 同级任务目录的阶段 `task.json`。如果执行器没有报告用量，则显示“未提供”；历史记录也不会被估算补写。重新启动时会检查 API 与 Compose 服务状态，避免对已运行的服务再次构建启动。

桌面模板默认 `runtime.output_language: zh-CN`。Dispatcher 对初始化、规划、探索和收尾五类提示词追加输出语言要求，事实说明、行动描述、总结及报告使用简体中文；JSON 字段、命令、标识符及原始证据保留原文。可选择 English 或跟随原提示词，核心配置未指定语言时沿用旧行为。历史任务的数据库与报告不会自动改写，第三方工具原始日志也不会强制翻译。

报告的具体文件名由任务与 Agent 决定，通常位于 `output/<项目 ID>/workspace/` 的子目录。控制中心和设置页均提供“打开任务文件／产物”入口，图页的“执行记录”可打开项目或阶段目录。阶段归档位于 `workspace/.cairn/runs/<阶段>/`，包含 `task.json`、`stdout.log`、`stderr.log`；Codex 会话在项目的 `codex/` 子目录。

应用图标由图像生成工具生成，使用石标与图节点主题。源图为 `assets/cairn.png`，Windows 多尺寸图标为 `assets/cairn.ico`；构建时嵌入 EXE，运行时用于窗口、控制中心和关于页。图标生成说明见 [图标来源](assets/README.md)。

## 构建

在 Windows 上双击 `desktop\build_windows.bat`，或从仓库根目录运行：

```powershell
desktop\build_windows.bat
```

批处理脚本会在 `desktop\build\.venv` 创建独立的 Python 构建环境，并在缺少构建依赖时安装 PyInstaller、pywebview 6.2.1、PyYAML 和测试所需库。唯一产物是 `desktop\dist_windows\CairnDesktop.exe`。构建前请退出正在运行的桌面程序（包括托盘进程），以便覆盖旧 EXE；构建脚本会清理早期版本遗留的 `*-update.exe`。Windows EXE 须在 Windows 上构建。构建脚本生成运行包后，也可以用 `python desktop/web_main.py` 直接调试新界面。`gui.py` 和原生 Canvas 图保留为旧实现，不是当前 EXE 的入口。

运行包保留原项目 `LICENSE`，构建时收集第三方依赖声明至 `app/licenses/THIRD_PARTY_NOTICES.txt`，并在可用时保留 Python 许可证。原图脚本仍使用仓库自带的资源，不依赖在线 CDN。

## 运行

1. 启动 Docker Desktop，并确保使用 Linux 容器。
2. 运行 `CairnDesktop.exe`，在“设置”页填写 DeepSeek API Key、选择模型与任务输出语言并保存，然后在“控制中心”点击“构建并启动”。
3. 点击“任务过程图”，在列表中创建任务或选择已有任务。也可打开 `http://127.0.0.1:8000` 使用原 Cairn Web 界面。
4. 使用“停止服务”停止当前任务和 Cairn 的 Compose 服务。

首次构建需要下载体积较大的 `linux/amd64` Kali Worker 镜像，并构建 Cairn 应用镜像。若靶站运行在 Windows 主机上，请在任务 URL 中使用 `host.docker.internal` 作为主机名；可从容器访问的外部 URL 可以直接填写。桌面程序不会安装或自动启动 Docker Desktop。

## 本地检查

```powershell
python -m py_compile desktop/core.py desktop/single_instance.py desktop/web_main.py desktop/web_host.py desktop/web_service.py desktop/build.py
python desktop/smoke_test.py
python desktop/test_graph_data.py
python desktop/test_web_host.py
python desktop/test_web_service.py
python desktop/webview_smoke.py
```

冒烟测试覆盖运行包解压、配置生成、旧数据迁移、Compose 配置和 EXE 单实例行为。图数据测试覆盖只读查询、分支汇合、未完成目标、循环数据和节点日志关联。HTTP 测试覆盖原资源、离线查询/快照、节点归档、界面偏好及请求边界。WebView2 测试在真实桌面窗口中检查连线点击、节点日志、Dagre/Klay/ELK、回放及刷新保留视角；测试通过 WebView2 的自身截图接口捕获应用内容，不读取其他窗口。历史任务截图使用 `python desktop/webview_smoke.py --storage desktop/dist_windows/CairnDesktopData`，只读取已有任务，不运行新任务。输出截图仅用于本地检查，不提交到仓库。
