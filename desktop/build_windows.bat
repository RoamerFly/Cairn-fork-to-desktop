@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%build\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    python --version >nul 2>&1
    if not errorlevel 1 (
        python -m venv "%SCRIPT_DIR%build\.venv"
    ) else (
        py -3 --version >nul 2>&1
        if errorlevel 1 (
            echo Python 3 is required to build CairnDesktop.exe.
            exit /b 1
        )
        py -3 -m venv "%SCRIPT_DIR%build\.venv"
    )
    if errorlevel 1 goto :failed
)

"%VENV_PY%" -c "import PyInstaller, customtkinter, PIL, webview, yaml, importlib.metadata; assert importlib.metadata.version('pywebview') == '6.2.1'" >nul 2>&1
if errorlevel 1 (
    "%VENV_PY%" -m pip install pyinstaller customtkinter pillow pywebview==6.2.1 pyyaml
    if errorlevel 1 goto :failed
)

pushd "%SCRIPT_DIR%.."
if errorlevel 1 goto :failed
"%VENV_PY%" "%SCRIPT_DIR%build.py"
set "BUILD_RESULT=%ERRORLEVEL%"
popd
if not "%BUILD_RESULT%"=="0" goto :failed

echo Build complete: "%SCRIPT_DIR%dist_windows\CairnDesktop.exe"
exit /b 0

:failed
echo Build failed.
exit /b 1
