# 一鍵重新打包 BMS FW Validation（GUI 版）
# 用法：在 PowerShell 進入 ai_workspace 目錄，執行 .\build.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "[1/3] 重建前端 (pnpm build)..." -ForegroundColor Cyan
Push-Location "$root\frontend"
& pnpm build
if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error "前端 build 失敗"; exit 1 }
Pop-Location

Write-Host ""
Write-Host "[2/3] PyInstaller 打包..." -ForegroundColor Cyan
Push-Location $root
& "$root\venv-ai\Scripts\pyinstaller.exe" app_gui.spec --distpath dist_exe_gui --workpath build_tmp_gui --noconfirm 2>&1 | Out-Null
Pop-Location

$exePath = "$root\dist_exe_gui\BMS-FW-Validation\BMS-FW-Validation.exe"
if (-not (Test-Path $exePath)) {
    Write-Error "PyInstaller 打包失敗，找不到 $exePath"
    exit 1
}

Write-Host ""
Write-Host "[3/3] 複製 .env..." -ForegroundColor Cyan
$srcEnv = "$root\.env"
$dstEnv = "$root\dist_exe_gui\BMS-FW-Validation\.env"
if (Test-Path $srcEnv) {
    Copy-Item $srcEnv $dstEnv -Force
    Write-Host "  .env 已複製"
} else {
    Write-Warning "  找不到 $srcEnv，請建立後再執行"
}

Write-Host ""
Write-Host "完成" -ForegroundColor Green
Write-Host "  輸出: $exePath"
