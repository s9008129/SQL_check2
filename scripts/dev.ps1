<#
.SYNOPSIS
  本機開發：同時啟動後端 (FastAPI/uvicorn) 與前端 (Vite dev server)。

.DESCRIPTION
  不需要 Docker、不需要真實 Ollama，適合日常前後端整合開發。
    - 後端：uv run uvicorn app.main:app --reload --port 8000（純 HTTP，本機開發不需要 TLS）
    - 前端：npm run dev（Vite dev server，已設定 proxy /api -> http://localhost:8000）
    - 假 Ollama（可選，-WithFakeOllama）：python scripts/fake_ollama.py --mode normal --port 11434

.PARAMETER WithFakeOllama
  同時啟動 scripts/fake_ollama.py 模擬 Ollama，讓 /api/analyze（include_ai=true）在沒有真實
  Ollama 的開發機上也有東西可打。

.EXAMPLE
  .\scripts\dev.ps1
.EXAMPLE
  .\scripts\dev.ps1 -WithFakeOllama
#>
param(
    [switch]$WithFakeOllama
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$scriptsDir = Join-Path $root "scripts"

if (-not (Test-Path (Join-Path $backendDir ".venv"))) {
    Write-Host "後端尚未安裝依賴，執行 uv sync --group dev ..." -ForegroundColor Yellow
    Push-Location $backendDir
    uv sync --group dev
    Pop-Location
}

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "前端尚未安裝依賴，執行 npm install ..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install
    Pop-Location
}

$procs = @()

try {
    if ($WithFakeOllama) {
        $fakeOllamaScript = Join-Path $scriptsDir "fake_ollama.py"
        if (Test-Path $fakeOllamaScript) {
            Write-Host "啟動假 Ollama（scripts/fake_ollama.py, port 11434）..." -ForegroundColor Cyan
            $procs += Start-Process -FilePath "uv" `
                -ArgumentList "run", "python", "fake_ollama.py", "--mode", "normal", "--port", "11434" `
                -WorkingDirectory $backendDir -PassThru -NoNewWindow
            $env:OLLAMA_BASE_URL = "http://localhost:11434"
        } else {
            Write-Host "找不到 scripts/fake_ollama.py，略過假 Ollama 啟動。" -ForegroundColor Yellow
        }
    }

    Write-Host "啟動後端（uvicorn --reload, http://localhost:8000）..." -ForegroundColor Cyan
    $backendProc = Start-Process -FilePath "uv" `
        -ArgumentList "run", "uvicorn", "app.main:app", "--reload", "--port", "8000" `
        -WorkingDirectory $backendDir -PassThru -NoNewWindow
    $procs += $backendProc

    Write-Host "啟動前端（vite dev server, http://localhost:5173）..." -ForegroundColor Cyan
    $frontendProc = Start-Process -FilePath "npm" `
        -ArgumentList "run", "dev" `
        -WorkingDirectory $frontendDir -PassThru -NoNewWindow
    $procs += $frontendProc

    Write-Host ""
    Write-Host "後端：http://localhost:8000/api/health" -ForegroundColor Green
    Write-Host "前端：http://localhost:5173" -ForegroundColor Green
    Write-Host "按 Ctrl+C 結束（會一併關閉後端與前端）..." -ForegroundColor Yellow

    Wait-Process -Id ($procs | Select-Object -ExpandProperty Id)
}
finally {
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
