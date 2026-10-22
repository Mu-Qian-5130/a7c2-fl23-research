# 可选启动脚本。Start.cmd 是纯批处理，不会调用本文件，也不需要本文件。
# 本文件同时兼容 Windows 自带的 5.1 与 7.x，只在你主动运行
#   powershell -ExecutionPolicy Bypass -File Start.ps1
# 时才生效；不需要额外安装任何新版脚本宿主。

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host '正在建立本工具专用的 Python 环境，请先安装 Python 3.10 或更新版。'
    & py -3 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '无法建立 Python 环境，请先安装 Python 3.10 或更新版。' }
}
& $pythonPath -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.10 或更新版。' }
& $pythonPath -c 'import usb, libusb_package, Cryptodome, yaml'
if ($LASTEXITCODE -ne 0) {
    Write-Host '第一次使用正在安装必要组件，需要网络连接。'
    & $pythonPath -m pip install --requirement (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '组件安装失败，尚未连接相机。' }
}

foreach ($folder in @('workdir', 'backup')) {
    $path = Join-Path $PSScriptRoot $folder
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

& $pythonPath (Join-Path $PSScriptRoot 'app.py') check-package
if ($LASTEXITCODE -ne 0) { throw '套件检查失败，尚未连接相机。' }
& $pythonPath (Join-Path $PSScriptRoot 'gui.py')
