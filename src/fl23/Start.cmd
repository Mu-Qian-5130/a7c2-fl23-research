@echo off
rem 纯批处理启动器：不调用 Windows 的脚本宿主，也不要求装新版跨平台脚本宿主。
rem 与旧版 Start.ps1 逻辑一致：建虚拟环境 - 装依赖 - 套件自检 - 启动界面。
rem 注意：会被重新赋值的变量不要在括号块里用 %VAR% 展开（会拿到块解析时的旧值），
rem       所以这里一律走 goto 线性流程；调用外部程序也统一加 call。
setlocal EnableExtensions
cd /d "%~dp0"
title A7C II FL2 / FL3 预览版

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PY="
set "LAUNCHER="

rem 1) 排错用：可用 A7C2_PYTHON 指定解释器
if not defined A7C2_PYTHON goto :use_venv
if not exist "%A7C2_PYTHON%" (
    echo [错误] A7C2_PYTHON 指向的文件不存在：%A7C2_PYTHON%
    pause
    exit /b 1
)
set "PY=%A7C2_PYTHON%"
goto :have_python

rem 2) 优先用本工具自带的虚拟环境
:use_venv
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
    goto :have_python
)

rem 3) 找一个 3.10 以上的解释器来创建虚拟环境
call :find_launcher
if defined LAUNCHER goto :make_venv
echo [错误] 没有找到 Python 3.10 或更新版，请先安装后再运行。
echo        https://www.python.org/downloads/
pause
exit /b 1

:make_venv
echo 正在建立本工具专用的 Python 环境，第一次运行需要一点时间...
echo 使用解释器：%LAUNCHER%
call %LAUNCHER% -m venv "%~dp0.venv"
if not errorlevel 1 goto :venv_done
echo [错误] 无法建立 Python 环境，请确认已安装 Python 3.10 或更新版。
pause
exit /b 1

:venv_done
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
    goto :have_python
)
echo [错误] 虚拟环境建立后仍找不到 python.exe，请删除 .venv 后重试。
pause
exit /b 1

rem 4) 到这里 %PY% 一定已经确定
:have_python
call "%PY%" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)"
if not errorlevel 1 goto :check_deps
echo [错误] 需要 Python 3.10 或更新版（当前：%PY%）。
pause
exit /b 1

rem 5) 依赖
:check_deps
call "%PY%" -c "import usb, libusb_package, Cryptodome, yaml" >nul 2>nul
if not errorlevel 1 goto :make_dirs
echo 第一次运行，正在安装必要组件（需要网络连接）...
call "%PY%" -m pip install --requirement "%~dp0requirements.txt"
if not errorlevel 1 goto :make_dirs
echo [错误] 组件安装失败，尚未连接相机。
pause
exit /b 1

rem 6) 工作目录与备份目录
:make_dirs
if not exist "%~dp0workdir" mkdir "%~dp0workdir"
if not exist "%~dp0backup" mkdir "%~dp0backup"

rem 7) 套件自检，然后启动界面
call "%PY%" "%~dp0app.py" check-package
if not errorlevel 1 goto :launch_gui
echo [错误] 套件检查失败，尚未连接相机。
pause
exit /b 1

:launch_gui
if not "%~1"=="" goto :launch_cli
call "%PY%" "%~dp0gui.py"
if not errorlevel 1 exit /b 0
pause
exit /b 1

:launch_cli
call "%PY%" "%~dp0app.py" %*
exit /b %errorlevel%

:find_launcher
set "LAUNCHER="
where py >nul 2>nul
if errorlevel 1 goto :try_python
call py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "LAUNCHER=py -3"
if defined LAUNCHER goto :eof
:try_python
where python >nul 2>nul
if errorlevel 1 goto :eof
call python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "LAUNCHER=python"
goto :eof
