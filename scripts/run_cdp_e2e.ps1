<#
.SYNOPSIS
  一键执行 CDP + E2E 全套测试
.DESCRIPTION
  1. 检查后端服务运行状态
  2. 启动 Tauri（带 CDP 端口 9223）
  3. 运行后端 API E2E 测试
  4. 运行 CDP UI 测试
  5. 生成 HTML 报告
  6. 关闭 Tauri
.PARAMETER SkipTauriStart
  如果 Tauri 已运行则跳过启动
.PARAMETER SkipBackendCheck
  跳过后端检查
.PARAMETER TauriExe
  Tauri exe 路径
.PARAMETER CdpPort
  CDP 端口，默认 9223
#>
[CmdletBinding()]
param(
    [switch]$SkipTauriStart,
    [switch]$SkipBackendCheck,
    [string]$TauriExe = "release\RAG知识库平台\RAG知识库平台.exe",
    [int]$CdpPort = 9223
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
Set-Location $root

Write-Host "=== CDP + E2E 全方位测试 ===" -ForegroundColor Cyan
Write-Host "Root: $root"
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# 1. 检查后端
if (-not $SkipBackendCheck) {
    Write-Host "`n[1/5] 检查后端服务..." -ForegroundColor Yellow
    try {
        $r = Invoke-RestMethod "http://localhost:8000/api/v1/system/status" -TimeoutSec 5
        Write-Host "  Backend OK" -ForegroundColor Green
    } catch {
        Write-Error "Backend not running on :8000. Start it first."
        exit 1
    }
}

# 2. 启动 Tauri
$tauriStarted = $false
if (-not $SkipTauriStart) {
    Write-Host "`n[2/5] 启动 Tauri (CDP port $CdpPort)..." -ForegroundColor Yellow
    & "$root\scripts\start_tauri_with_cdp.ps1" -CdpPort $CdpPort -TauriExe $TauriExe
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to start Tauri with CDP"
        exit 1
    }
    $tauriStarted = $true
} else {
    Write-Host "`n[2/5] Skip Tauri start (already running)" -ForegroundColor Yellow
}

# 3. 运行后端 API E2E
Write-Host "`n[3/5] 运行后端 API E2E 测试..." -ForegroundColor Yellow
Push-Location "$root\backend"
$apiTests = @(
    "tests/e2e/test_01_auth_e2e.py",
    "tests/e2e/test_02_users_e2e.py",
    "tests/e2e/test_03_kb_e2e.py",
    "tests/e2e/test_04_documents_e2e.py",
    "tests/e2e/test_05_chat_sse_e2e.py",
    "tests/e2e/test_06_feedback_e2e.py",
    "tests/e2e/test_07_evaluation_e2e.py",
    "tests/e2e/test_08_system_e2e.py",
    "tests/e2e/test_09_security_e2e.py",
    "tests/e2e/test_10_rate_limit_e2e.py",
    "tests/e2e/test_16_tauri_config.py"
)
$apiResult = & poetry run python -m pytest $apiTests -v --tb=short --continue-on-collection-errors 2>&1
$apiExit = $LASTEXITCODE
Write-Host $apiResult
Pop-Location

# 4. 运行 CDP UI 测试
Write-Host "`n[4/5] 运行 CDP UI 测试..." -ForegroundColor Yellow
Push-Location "$root\backend"
$cdpTests = @(
    "tests/e2e/test_11_cdp_login.py",
    "tests/e2e/test_12_cdp_kb.py",
    "tests/e2e/test_13_cdp_chat.py",
    "tests/e2e/test_14_cdp_csp.py",
    "tests/e2e/test_15_cdp_state_sync.py",
    "tests/e2e/test_17_tauri_mixed_content.py"
)
$cdpResult = & poetry run python -m pytest $cdpTests -v --tb=short --continue-on-collection-errors 2>&1
$cdpExit = $LASTEXITCODE
Write-Host $cdpResult
Pop-Location

# 5. 关闭 Tauri
if ($tauriStarted -and (Test-Path ".tauri_cdp_pid")) {
    Write-Host "`n[5/5] 关闭 Tauri..." -ForegroundColor Yellow
    $pid_val = Get-Content ".tauri_cdp_pid"
    Stop-Process -Id $pid_val -Force -ErrorAction SilentlyContinue
    Remove-Item ".tauri_cdp_pid" -Force -ErrorAction SilentlyContinue
}

# 汇总
Write-Host "`n=== 测试完成 ===" -ForegroundColor Cyan
Write-Host "API E2E exit code: $apiExit"
Write-Host "CDP UI exit code: $cdpExit"
Write-Host "HTML 报告位置: backend\tests\e2e\reports\"

# 报告路径
$reports = Get-ChildItem "$root\backend\tests\e2e\reports\e2e_report_*.html" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($reports) {
    Write-Host "最新报告: $($reports.FullName)"
    Start-Process $reports.FullName  # 自动打开浏览器
}

if ($apiExit -eq 0 -and $cdpExit -eq 0) {
    Write-Host "ALL PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "SOME FAILED" -ForegroundColor Red
    exit 1
}
