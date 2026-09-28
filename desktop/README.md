# Cairn Windows 桌面版

`CairnDesktop.exe` 是 Cairn 的单文件 Windows 图形启动器，用于配置和运行 Docker 中的 Cairn 服务及 Codex Worker。界面采用中文，设计参考见 [中文设计稿](design/cairn-desktop-mockup-cn.png)。程序内含 Cairn 源码、锁文件、Dockerfile、Compose 配置和 DeepSeek/Codex 配置模板；目标电脑无需另装 Python，但需要 Docker Desktop 运行 Linux 容器。Windows 命名互斥量保证界面只运行一个实例，重复打开会切回已打开的窗口。

首次启动时，程序文件会解压到 `%LOCALAPPDATA%\CairnDesktop\app`；配置和数据库保存在 `%LOCALAPPDATA%\CairnDesktop\data`。DeepSeek API Key 以明文保存在当前 Windows 用户目录下的 `data\dispatch.yaml`，不会被打包进 EXE。旧版 `runtime` 目录中的配置和数据会复制到新目录，旧文件保留。若在 EXE 旁创建 `portable.flag`，数据将保存到同目录的 `CairnDesktopData`；也可设置 `CAIRN_DESKTOP_STORAGE_ROOT` 指定存储根目录。Web 服务仅监听 `127.0.0.1:8000`。

## 构建

在 Windows 上运行：

```powershell
python -m pip install pyinstaller customtkinter pillow
python desktop/build.py
```

产物是 `dist\CairnDesktop.exe`。Windows EXE 须在 Windows 上构建。构建脚本生成运行包后，也可以用 `python desktop/gui.py` 直接调试界面。

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
