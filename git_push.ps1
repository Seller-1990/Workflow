# 提交代码脚本

Write-Host "开始提交代码到 GitHub..." -ForegroundColor Cyan

# 检查 git 命令
if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 未找到 git 命令，请安装 Git 并添加到环境变量。" -ForegroundColor Red
    Pause
    Exit
}

# 添加更改
git add .

# 提交
$commitMsg = Read-Host "请输入提交信息 (直接回车默认: feat: complete workflow management app v1.0)"
if ([string]::IsNullOrWhiteSpace($commitMsg)) {
    $commitMsg = "feat: complete workflow management app v1.0"
}
git commit -m "$commitMsg"

# 推送
Write-Host "正在推送..." -ForegroundColor Cyan
git push

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ 推送成功！" -ForegroundColor Green
}
else {
    Write-Host "❌ 推送失败，请检查网络或配置。" -ForegroundColor Red
}

Pause
