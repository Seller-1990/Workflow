# 尝试找到可用的 Python 命令
$pythonCmd = "python"
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        $pythonCmd = "py"
    }
    else {
        Write-Host "❌ 未找到 Python 环境，请先安装 Python 并添加到 PATH。" -ForegroundColor Red
        Pause
        Exit
    }
}

Write-Host "使用 Python 命令: $pythonCmd" -ForegroundColor Cyan

# 检查/安装 PyInstaller
if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "正在安装 PyInstaller..." -ForegroundColor Cyan
    & $pythonCmd -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
}

# 清理旧的构建文件
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

# 执行打包
Write-Host "开始打包..." -ForegroundColor Green
pyinstaller build.spec --noconfirm --clean

# 检查结果
if (Test-Path "dist/工作流管理/工作流管理.exe") {
    Write-Host "✅ 打包成功！" -ForegroundColor Green
    Write-Host "程序位置: .\dist\工作流管理\工作流管理.exe" -ForegroundColor Yellow
}
else {
    Write-Host "❌ 打包失败，请检查错误信息。" -ForegroundColor Red
}

Pause
