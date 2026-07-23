<#
.SYNOPSIS
  Start Tauri desktop app with CDP debugging port
.DESCRIPTION
  Uses port 9223 (avoid 9222 RCE risk), for E2E testing only.
  Tauri WebView2 requires WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS env var
  (command-line --remote-debugging-port is NOT supported by WebView2).
.PARAMETER CdpPort
  CDP port, default 9223
.PARAMETER TauriExe
  Tauri exe path, auto-detected if empty
#>
[CmdletBinding()]
param(
    [int]$CdpPort = 9223,
    [string]$TauriExe = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
Set-Location $root

# Auto-detect exe if not specified (avoid Chinese path encoding issues)
if ([string]::IsNullOrEmpty($TauriExe)) {
    $patterns = @(
        "release\rag-platform-desktop.exe",
        "release\*\rag-platform-desktop.exe"
    )
    foreach ($pattern in $patterns) {
        $found = Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $TauriExe = $found.FullName
            break
        }
    }
}

if ([string]::IsNullOrEmpty($TauriExe) -or -not (Test-Path $TauriExe)) {
    Write-Error "Tauri exe not found in release/ directory (cwd: $(Get-Location))"
    exit 1
}

$exePath = Resolve-Path $TauriExe
Write-Host "Starting Tauri with CDP port $CdpPort..."
Write-Host "Exe: $exePath"

# WebView2 CDP requires env var (not command-line arg)
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$CdpPort"
Write-Host "Env: WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"

# Start Tauri (inherit env var)
$proc = Start-Process -FilePath $exePath -PassThru
Write-Host "Tauri PID: $($proc.Id)"
Write-Host "CDP endpoint: http://localhost:$CdpPort/json"

# Wait for CDP endpoint to be ready
$maxWait = 45
$ready = $false
for ($i = 1; $i -le $maxWait; $i++) {
    try {
        $response = Invoke-RestMethod "http://localhost:$CdpPort/json" -TimeoutSec 2
        if ($response) {
            Write-Host "CDP is ready (waited ${i}s)"
            Write-Host "Targets: $($response.Count)"
            $proc.Id | Out-File ".tauri_cdp_pid" -Encoding ascii
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Error "CDP endpoint not ready after ${maxWait}s"
    exit 1
}

Write-Host "Tauri started successfully with CDP"
exit 0
