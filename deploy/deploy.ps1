#Requires -Version 7.0
<#
.SYNOPSIS
    SQLCheck 2.0 - 正式主機一鍵部署 (Phase 7)。

.DESCRIPTION
    在正式主機 (Windows 11 + Docker Desktop + Windows 原生 Ollama) 上，
    以系統管理員身分執行本腳本，完成：Preflight 檢查、設定 Ollama 對外監聽、
    設定 Windows 防火牆規則、準備 .env、產生自簽 HTTPS 憑證、建置並啟動
    Docker 容器、健康檢查、smoke test。

    詳細說明見同目錄 README-deploy.md。

.PARAMETER CheckOnly
    只執行 Preflight 檢查並印出結果摘要，不做任何變更 (不啟動 Docker Desktop、
    不動防火牆、不動 .env/憑證、不建置/啟動容器)。用於在開發機 (無 Docker) 上
    確認腳本本身邏輯正常。

.PARAMETER SkipBuild
    略過 `docker compose build`，直接以現有映像檔執行 `docker compose up -d`。

.PARAMETER Rollback
    停止目前容器，並嘗試回復到上一次部署標記的 `sqlcheck-app:prev` 映像檔。

.PARAMETER Down
    執行 `docker compose down` 後結束，不做其他任何事。

.PARAMETER ProductionIp
    正式主機區網 IP，會寫入憑證 SAN 並用於部署完成後開啟瀏覽器。

.PARAMETER OllamaModel
    正式主機上應已安裝的 Ollama 模型標籤，寫入 .env 的 OLLAMA_MODEL。

.PARAMETER DockerRemoteAddress
    找不到 vEthernet (WSL) 介面時，Ollama (11434) 防火牆規則改用的來源位址範圍
    (CIDR)。實際範圍依 Docker Desktop 網路模式而異，必要時請調整此參數。
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipBuild,
    [switch]$Rollback,
    [switch]$Down,
    [string]$ProductionIp = '10.97.15.58',
    [string]$OllamaModel = 'gemma4:31b',
    [string]$DockerRemoteAddress = '172.16.0.0/12'
)

$ErrorActionPreference = 'Stop'
# This script inspects $LASTEXITCODE itself after every docker/ollama/certutil
# call and turns failures into actionable messages. Pin the PowerShell 7.4+
# native-command preference off so a non-zero exit code can never be
# escalated into a raw terminating error before those checks run, regardless
# of the host's PowerShell version or profile.
$PSNativeCommandUseErrorActionPreference = $false

# ============================================================================
# Paths (script-scoped constants for this run)
# ============================================================================
$script:DeployRoot     = $PSScriptRoot
$script:RepoRoot        = Split-Path -Parent $PSScriptRoot
$script:LogsDir         = Join-Path $script:DeployRoot 'logs'
$script:CertsDir        = Join-Path $script:RepoRoot 'certs'
$script:DataDir         = Join-Path $script:RepoRoot 'data'
$script:EnvFile         = Join-Path $script:RepoRoot '.env'
$script:EnvExampleFile  = Join-Path $script:RepoRoot '.env.example'
$script:BuiltThisRun    = $false   # set by Step 5 when it has to build the image itself

# ============================================================================
# Output helpers - Write-Host progress output (also captured by Start-Transcript)
# ============================================================================
function Write-Step { param([string]$Message) Write-Host "`n=== $Message ===" -ForegroundColor Cyan }
function Write-Info { param([string]$Message) Write-Host "  [INFO] $Message" -ForegroundColor Gray }
function Write-Ok   { param([string]$Message) Write-Host "  [ OK ] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "  [FAIL] $Message" -ForegroundColor Red }

# ============================================================================
# Thin passthrough wrapper: always run `docker compose` from the repo root
# (where docker-compose.yml / .env / ./certs live), regardless of deploy.ps1's
# own working directory. Deliberately a *simple* function (no param() block)
# so that dash-prefixed docker/compose flags (--rm, --build, ...) land in the
# automatic $args array untouched instead of PowerShell trying (and failing)
# to bind them to named parameters.
# ============================================================================
function Invoke-DockerCompose {
    Push-Location -Path $script:RepoRoot
    try {
        # `| Out-Host` is load-bearing: everything a native command writes to
        # stdout inside a PowerShell function becomes part of that function's
        # *return value*. Without it, `$x = Invoke-DockerCompose build` made $x
        # an array of every BuildKit log line followed by the exit code, so
        # `$x -ne 0` was always truthy and error messages dumped the whole
        # build log (observed on the first production deploy). Out-Host prints
        # the log for the operator but keeps it out of the pipeline; the
        # function then returns only the integer exit code.
        & docker compose @args | Out-Host
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    return $exitCode
}

# ============================================================================
# Preflight check primitives
# ============================================================================
function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-DockerInfo {
    try {
        docker info *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-DockerReady {
    <#
        Returns @{ Success = [bool]; Message = [string] }.
        -NoLaunch: only probe current state, never try to start Docker Desktop
        or poll/wait for it (used under -CheckOnly so the check stays fast and
        side-effect-free, e.g. on a dev machine with no Docker at all).
    #>
    param([switch]$NoLaunch)

    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        return @{ Success = $false; Message = 'docker CLI 未安裝或不在 PATH 中。請先在正式主機安裝 Docker Desktop。' }
    }

    if (Test-DockerInfo) {
        return @{ Success = $true; Message = 'Docker Desktop 引擎已在執行。' }
    }

    if ($NoLaunch) {
        return @{ Success = $false; Message = 'docker CLI 存在，但 Docker 引擎目前未回應 (docker info 失敗)。-CheckOnly 模式不會嘗試啟動 Docker Desktop；請確認 Docker Desktop 是否已啟動後再重新檢查。' }
    }

    Write-Warn 'Docker 引擎未回應，嘗試啟動 Docker Desktop...'
    $dockerDesktopExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktopExe)) {
        return @{ Success = $false; Message = "找不到 Docker Desktop 執行檔: $dockerDesktopExe。請確認已安裝 Docker Desktop，或手動啟動後重新執行本腳本。" }
    }

    try {
        Start-Process -FilePath $dockerDesktopExe -ErrorAction Stop | Out-Null
    } catch {
        return @{ Success = $false; Message = "啟動 Docker Desktop 失敗: $($_.Exception.Message)" }
    }

    $maxWaitSeconds = 180
    $intervalSeconds = 5
    $elapsed = 0
    while ($elapsed -lt $maxWaitSeconds) {
        Start-Sleep -Seconds $intervalSeconds
        $elapsed += $intervalSeconds
        Write-Info "等待 Docker 引擎啟動... ($elapsed 秒 / $maxWaitSeconds 秒)"
        if (Test-DockerInfo) {
            return @{ Success = $true; Message = "Docker Desktop 已於約 $elapsed 秒後就緒。" }
        }
    }

    return @{ Success = $false; Message = "Docker Desktop 在 $maxWaitSeconds 秒內未就緒。請手動開啟 Docker Desktop，確認其引擎狀態列為 Running 後再重新執行本腳本。" }
}

function Test-OllamaModelInstalled {
    <# Returns @{ Success = [bool]; Message = [string]; Models = [string[]] } via `ollama list` (CLI). #>
    param([string]$ModelName)

    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaCmd) {
        return @{ Success = $false; Message = 'ollama CLI 未安裝或不在 PATH 中。請先在正式主機安裝 Ollama for Windows。'; Models = @() }
    }

    $listOutput = & ollama list 2>$null
    $listExitCode = $LASTEXITCODE

    if ($listExitCode -ne 0) {
        return @{ Success = $false; Message = "執行 'ollama list' 失敗 (結束碼 $listExitCode)。Ollama 服務可能尚未啟動。"; Models = @() }
    }

    $lines = @($listOutput | Where-Object { $_ -match '\S' })
    $matched = @($lines | Where-Object { $_ -match [Regex]::Escape($ModelName) })

    if ($matched.Count -gt 0) {
        return @{ Success = $true; Message = "已找到模型 $ModelName。"; Models = $lines }
    }
    return @{ Success = $false; Message = "未找到模型 $ModelName。"; Models = $lines }
}

function Test-OllamaModelViaApi {
    <# Returns @{ Success = [bool]; Message = [string] } via GET {ApiBase}/api/tags (HTTP API). #>
    param(
        [string]$ModelName,
        [string]$ApiBase = 'http://127.0.0.1:11434'
    )

    try {
        $response = Invoke-RestMethod -Uri "$ApiBase/api/tags" -TimeoutSec 5 -ErrorAction Stop
    } catch {
        return @{ Success = $false; Message = "無法連線至 Ollama API ($ApiBase/api/tags): $($_.Exception.Message)" }
    }

    $names = @($response.models | ForEach-Object { $_.name })
    if ($names -contains $ModelName) {
        return @{ Success = $true; Message = "透過 API 確認模型 $ModelName 可用。" }
    }
    if (($names -join "`n") -match [Regex]::Escape($ModelName)) {
        return @{ Success = $true; Message = "透過 API 確認模型 $ModelName 可用 (模糊比對)。" }
    }
    return @{ Success = $false; Message = "透過 API 查詢，未在已安裝模型清單中找到 $ModelName。目前清單: $($names -join ', ')" }
}

# ============================================================================
# Step 1/6: Preflight
# ============================================================================
function Invoke-Preflight {
    Write-Step 'Step 1/6: Preflight 檢查'

    $results = [ordered]@{}

    $isAdmin = Test-IsAdministrator
    $results['系統管理員權限'] = $isAdmin
    if ($isAdmin) {
        Write-Ok '目前以系統管理員身分執行。'
    } else {
        Write-Fail '未以系統管理員身分執行。請關閉本視窗，改用「以系統管理員身分執行」開啟 PowerShell 7 (pwsh)，再重新執行本腳本。'
    }

    $dockerCheck = Test-DockerReady -NoLaunch:$CheckOnly
    $results['Docker Desktop 引擎'] = $dockerCheck.Success
    if ($dockerCheck.Success) {
        Write-Ok $dockerCheck.Message
    } else {
        Write-Fail $dockerCheck.Message
    }

    $ollamaCheck = Test-OllamaModelInstalled -ModelName $OllamaModel
    $results["Ollama 模型 ($OllamaModel)"] = $ollamaCheck.Success
    if ($ollamaCheck.Success) {
        Write-Ok $ollamaCheck.Message
    } else {
        Write-Fail $ollamaCheck.Message
        if ($ollamaCheck.Models.Count -gt 0) {
            Write-Info '目前已安裝的模型清單:'
            foreach ($m in $ollamaCheck.Models) { Write-Info "  - $m" }
        } else {
            Write-Info '無法取得已安裝模型清單 (Ollama 可能未安裝或尚未啟動)。'
        }
        Write-Info "請執行: ollama pull $OllamaModel"
    }

    return $results
}

# ============================================================================
# Step 2/6: Ollama host binding (skipped entirely under -CheckOnly by caller)
# ============================================================================
function Set-OllamaHostBinding {
    Write-Step 'Step 2/6: 設定 Ollama 對外監聽 (OLLAMA_HOST)'

    $desiredValue = '0.0.0.0:11434'
    $currentValue = [System.Environment]::GetEnvironmentVariable('OLLAMA_HOST', 'User')

    if ($currentValue -eq $desiredValue) {
        Write-Ok "OLLAMA_HOST 已設為 $desiredValue，不需變更，略過重啟 Ollama。"
        return
    }

    if ([string]::IsNullOrWhiteSpace($currentValue)) {
        Write-Info "目前未設定使用者層級的 OLLAMA_HOST，將設定為 $desiredValue..."
    } else {
        Write-Warn "目前 OLLAMA_HOST 為 '$currentValue'，將覆寫為 $desiredValue 以便容器可透過 host.docker.internal 存取。"
    }

    [System.Environment]::SetEnvironmentVariable('OLLAMA_HOST', $desiredValue, 'User')
    Write-Ok "已設定使用者層級環境變數 OLLAMA_HOST=$desiredValue。"

    Write-Info '正在停止現有的 Ollama processes 以套用新設定...'
    $procs = Get-Process -Name 'ollama*', 'ollama app' -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Ok '已停止現有的 Ollama processes。'
    } else {
        Write-Info '目前沒有偵測到執行中的 Ollama processes。'
    }

    # Ollama on Windows runs as a per-user tray app, not a system service.
    # Do NOT start it from this elevated/Administrator script - that would
    # launch it under the wrong user context and could create a duplicate
    # instance alongside the operator's normal tray-launched one. Ask the
    # operator to relaunch it themselves instead.
    Write-Host ''
    Write-Host '  >>> 請手動從「開始」功能表或系統匣重新啟動 Ollama (一般使用者身分，非提權) <<<' -ForegroundColor Yellow
    Write-Host '  腳本將輪詢等待 Ollama 重新上線 (最多 60 秒)...' -ForegroundColor Yellow
    Write-Host ''

    $maxWaitSeconds = 60
    $intervalSeconds = 3
    $elapsed = 0
    $reachable = $false
    while ($elapsed -lt $maxWaitSeconds) {
        Start-Sleep -Seconds $intervalSeconds
        $elapsed += $intervalSeconds
        try {
            $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 -ErrorAction Stop
            $reachable = $true
            break
        } catch {
            Write-Info "等待 Ollama 上線... ($elapsed 秒 / $maxWaitSeconds 秒)"
        }
    }

    if (-not $reachable) {
        throw "Ollama 在 $maxWaitSeconds 秒內未重新上線。請確認已從開始功能表重新啟動 Ollama，並確認防毒軟體/防火牆未阻擋 127.0.0.1:11434，然後重新執行本腳本。"
    }
    Write-Ok 'Ollama 已重新上線。'

    $modelCheck = Test-OllamaModelViaApi -ModelName $OllamaModel -ApiBase 'http://localhost:11434'
    if ($modelCheck.Success) {
        Write-Ok "重新啟動後確認模型 $OllamaModel 仍可用。"
    } else {
        throw "Ollama 重新啟動後，找不到模型 $OllamaModel。請執行 'ollama pull $OllamaModel' 後重新執行本腳本。($($modelCheck.Message))"
    }
}

# ============================================================================
# Step 3/6: Firewall (skipped entirely under -CheckOnly by caller)
# ============================================================================
function Set-FirewallRules {
    Write-Step 'Step 3/6: 設定 Windows 防火牆規則'

    # --- Rule 1: Ollama API (TCP 11434) ------------------------------------
    # SECURITY (PRD §46): "Windows Firewall 應限制 11434 不對一般區網任意開放" -
    # only the Docker container running as sqlcheck-app should ever be able
    # to reach the Windows-native Ollama instance on this host; it must never
    # be reachable from the general LAN. Prefer scoping the rule to Docker
    # Desktop's internal WSL vEthernet interface (container traffic arrives
    # over that adapter); fall back to restricting the *source address range*
    # to Docker's private network space if that adapter isn't present (e.g.
    # Docker Desktop running in Hyper-V mode instead of WSL2).
    $ollamaRuleName = 'SQLCheck - Ollama API (container only)'
    $existingOllamaRule = Get-NetFirewallRule -DisplayName $ollamaRuleName -ErrorAction SilentlyContinue
    if ($existingOllamaRule) {
        Write-Ok "防火牆規則 '$ollamaRuleName' 已存在，略過建立。"
    } else {
        $wslAdapter = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'vEthernet (WSL*' }
        try {
            if ($wslAdapter) {
                $interfaceAlias = @($wslAdapter)[0].Name
                New-NetFirewallRule -DisplayName $ollamaRuleName `
                    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434 `
                    -InterfaceAlias $interfaceAlias `
                    -Profile Any `
                    -Description 'Ollama API - 僅限 Docker (WSL) 介面存取，不對一般區網開放 (PRD §46)。' | Out-Null
                Write-Ok "已建立防火牆規則 '$ollamaRuleName' (限定介面: $interfaceAlias)。"
            } else {
                New-NetFirewallRule -DisplayName $ollamaRuleName `
                    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434 `
                    -RemoteAddress $DockerRemoteAddress `
                    -Profile Any `
                    -Description "Ollama API - 僅限 Docker 內部網段 ($DockerRemoteAddress) 存取，不對一般區網開放 (PRD §46)。找不到 vEthernet (WSL) 介面，改用來源位址範圍限制；請依實際 Docker Desktop 網路模式調整 -DockerRemoteAddress。" | Out-Null
                Write-Ok "已建立防火牆規則 '$ollamaRuleName' (限定來源位址: $DockerRemoteAddress)。"
            }
        } catch {
            Write-Warn "建立 Ollama 防火牆規則失敗: $($_.Exception.Message)。請手動確認 11434 埠僅限 Docker 存取，切勿對一般區網開放。"
        }
    }

    # --- Rule 2: HTTPS (TCP 443) - meant to be reached by colleagues' browsers
    $httpsRuleName = 'SQLCheck - HTTPS (LAN)'
    $existingHttpsRule = Get-NetFirewallRule -DisplayName $httpsRuleName -ErrorAction SilentlyContinue
    if ($existingHttpsRule) {
        Write-Ok "防火牆規則 '$httpsRuleName' 已存在，略過建立。"
    } else {
        try {
            # Domain/Private only (not Public) narrows exposure to trusted
            # network profiles. Not further scoped to a specific -RemoteAddress
            # LAN range here because that range isn't reliably knowable from
            # this script; operators can tighten it further, e.g.:
            #   Set-NetFirewallRule -DisplayName '<name>' -RemoteAddress <CIDR>
            New-NetFirewallRule -DisplayName $httpsRuleName `
                -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 `
                -Profile Domain,Private `
                -Description 'SQLCheck 2.0 Web UI - 供同仁瀏覽器透過 HTTPS 存取。' | Out-Null
            Write-Ok "已建立防火牆規則 '$httpsRuleName' (Profile: Domain, Private)。"
        } catch {
            Write-Warn "建立 HTTPS 防火牆規則失敗: $($_.Exception.Message)。請手動確認防火牆已允許 TCP 443 (Domain/Private 設定檔)。"
        }
    }
}

# ============================================================================
# Step 4/6: .env
# ============================================================================
function Initialize-EnvFile {
    Write-Step 'Step 4/6: 設定 .env'

    if (Test-Path $script:EnvFile) {
        Write-Ok ".env 已存在 ($script:EnvFile)，不覆寫既有設定。"
        return
    }

    if (-not (Test-Path $script:EnvExampleFile)) {
        throw "找不到範本檔案 $script:EnvExampleFile，無法建立 .env。請確認專案結構完整。"
    }

    Write-Info "複製 .env.example -> .env 並套用 OLLAMA_MODEL=$OllamaModel..."
    $content = Get-Content -Path $script:EnvExampleFile -Raw
    $updated = $content -replace '(?m)^OLLAMA_MODEL=.*$', "OLLAMA_MODEL=$OllamaModel"
    Set-Content -Path $script:EnvFile -Value $updated
    Write-Ok ".env 已建立於 $script:EnvFile (OLLAMA_MODEL=$OllamaModel)。"
}

# ============================================================================
# Step 5/6: TLS certificate
# ============================================================================
function Initialize-TlsCertificate {
    Write-Step 'Step 5/6: TLS 憑證'

    $certPath = Join-Path $script:CertsDir 'sqlcheck.crt'
    if (Test-Path $certPath) {
        Write-Ok "憑證已存在 ($certPath)，略過產生憑證。若要重新產生，請先手動刪除 .\certs 目錄下的檔案。"
        return
    }

    if (-not (Test-Path $script:CertsDir)) {
        New-Item -ItemType Directory -Path $script:CertsDir -Force | Out-Null
    }

    # `docker compose run` does NOT build a missing image — with both `build:`
    # and `image:` set it tries to *pull* the image name from Docker Hub and
    # fails ("pull access denied"). Build explicitly first.
    docker image inspect sqlcheck-app:latest *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Info '尚未建置映像檔，先執行 docker compose build (首次建置需下載 base image 與套件，可能需要數分鐘)...'
        $buildExit = Invoke-DockerCompose build
        if ($buildExit -ne 0) {
            throw "docker compose build 失敗 (結束碼 $buildExit)。請檢查上方輸出的錯誤訊息 (常見原因: 網路無法連上 Docker Hub / npm / PyPI、Dockerfile 建置錯誤、磁碟空間不足)。"
        }
        $script:BuiltThisRun = $true
        Write-Ok '映像檔建置完成。'
    }

    Write-Info "產生自我簽署憑證 (SAN 包含: $ProductionIp, $env:COMPUTERNAME, 127.0.0.1, localhost)..."
    # Deliberately NOT `docker compose run`: docker-compose.yml mounts ./certs
    # read-only (`:ro`) for the running service — correct hardening at runtime,
    # but it makes the one-shot generation step fail with "Read-only file
    # system" (the real cause of the exit-code-1 seen on the first production
    # deploy). A plain `docker run` on the freshly built image with an explicit
    # read-write bind mount keeps the service's :ro mount untouched while
    # letting this single step write the three certificate files.
    $certsMount = "$($script:CertsDir):/certs"
    & docker run --rm -v $certsMount sqlcheck-app:latest `
        python -m app.certgen --out-dir /certs --host $ProductionIp --host $env:COMPUTERNAME | Out-Host
    $certgenExit = $LASTEXITCODE

    if ($certgenExit -ne 0) {
        throw "憑證產生失敗 (certgen 結束碼 $certgenExit)。請檢查上方 certgen 印出的錯誤訊息 (常見原因: .\certs 目錄無法寫入、--host 參數格式錯誤)。"
    }
    if (-not (Test-Path $certPath)) {
        throw "certgen 回報成功，但找不到預期的憑證檔案 $certPath。請檢查 .\certs 目錄內容。"
    }
    Write-Ok "憑證已產生於 $script:CertsDir"

    $cerPath = Join-Path $script:CertsDir 'sqlcheck.cer'
    if (Test-Path $cerPath) {
        Write-Info '將憑證匯入本機「受信任的根憑證授權單位」存放區 (certutil -addstore Root)...'
        certutil -addstore Root $cerPath | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok '憑證已匯入本機信任的根憑證存放區。'
        } else {
            Write-Warn "certutil 匯入憑證失敗 (結束碼 $LASTEXITCODE)。此為非致命警告：本機瀏覽器仍可能顯示憑證不受信任的警告。其他同仁的機器也需要匯入才會信任，詳見 README-deploy.md。"
        }
    } else {
        Write-Warn "找不到 $cerPath，略過匯入本機信任存放區。其他機器仍需手動匯入 .cer 檔案才能信任此憑證，詳見 README-deploy.md。"
    }
}

# ============================================================================
# Health check polling helper (used by step 6)
# ============================================================================
function Wait-ForHealthCheck {
    param(
        [string]$Uri = 'https://localhost/api/health',
        [int]$MaxWaitSeconds = 90,
        [int]$IntervalSeconds = 3
    )

    $elapsed = 0
    while ($elapsed -lt $MaxWaitSeconds) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -SkipCertificateCheck -TimeoutSec 5 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                $body = $response.Content | ConvertFrom-Json
                return @{ Reachable = $true; Status = $body.status; AiAvailable = [bool]$body.ai_available }
            }
        } catch {
            # Not up yet - keep polling.
        }
        Start-Sleep -Seconds $IntervalSeconds
        $elapsed += $IntervalSeconds
        Write-Info "等待容器健康檢查通過... ($elapsed 秒 / $MaxWaitSeconds 秒)"
    }

    return @{ Reachable = $false; Status = $null; AiAvailable = $false }
}

# ============================================================================
# Step 6/6: Build & start
# ============================================================================
function Test-DataDirWritable {
    # SQL 蒐集檔 (app/services/sql_archive.py) 掛載為讀寫 volume (docker-compose.yml
    # 的 ./data:/data)。這個掛載能不能寫入只有在正式主機才驗證得到 (同一類問題見
    # tasks/lessons.md「正式主機首次建置：Step 5 憑證產生失敗」)，寫入失敗時
    # sql_archive.py 會靜默略過 (絕不影響 /api/analyze 回應)，代表使用者可能過了
    # 好幾週才發現蒐集檔是空的。這裡在啟動前就先探測，提早示警。
    if (-not (Test-Path $script:DataDir)) {
        try {
            New-Item -ItemType Directory -Path $script:DataDir -Force | Out-Null
        } catch {
            return $false
        }
    }
    $probePath = Join-Path $script:DataDir '.write-probe'
    try {
        Set-Content -Path $probePath -Value 'ok' -Encoding utf8 -ErrorAction Stop
        Remove-Item -Path $probePath -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Invoke-BuildAndStart {
    Write-Step 'Step 6/6: 建置映像檔並啟動容器'

    Write-Info '檢查 SQL 蒐集檔資料夾是否可寫入 (.\data)...'
    if (Test-DataDirWritable) {
        Write-Ok "SQL 蒐集檔資料夾可正常寫入 ($script:DataDir)。"
    } else {
        Write-Warn "資料夾 $script:DataDir 無法寫入。SQL 蒐集檔功能 (去識別化 SQL 統計用途) 將會靜默失效，但不影響網頁與 SQL 檢核本身。請確認資料夾權限，或於 .env 將 SQLCHECK_ARCHIVE_ENABLED 設為 false 明確停用。"
    }

    if (-not $SkipBuild) {
        if ($script:BuiltThisRun) {
            # The image was just built in Step 5 for certificate generation —
            # there is no *previous* deployment to preserve, and tagging the
            # brand-new build as :prev would make -Rollback a no-op.
            Write-Info '映像檔於本次執行的 Step 5 剛建置完成，尚無前一版可作為復原點，略過標記。'
        } else {
            Write-Info '將目前的映像檔標記為復原點 (sqlcheck-app:prev)...'
            docker tag sqlcheck-app:latest sqlcheck-app:prev 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok '已建立復原點映像檔 sqlcheck-app:prev。'
            } else {
                Write-Info '尚無既有的 sqlcheck-app:latest 映像檔可標記為復原點 (可能是首次部署)，略過。'
            }
        }

        Write-Info '建置並啟動容器中 (docker compose up -d --build)，首次建置可能需要數分鐘...'
        $exitCode = Invoke-DockerCompose up -d --build
        if ($exitCode -ne 0) {
            throw "docker compose up -d --build 失敗 (結束碼 $exitCode)。請檢查上方輸出的錯誤訊息 (常見原因: Dockerfile 建置錯誤、443 埠已被占用、磁碟空間不足)。"
        }
    } else {
        Write-Info '已指定 -SkipBuild，直接啟動既有映像檔 (docker compose up -d)...'
        $exitCode = Invoke-DockerCompose up -d
        if ($exitCode -ne 0) {
            throw "docker compose up -d 失敗 (結束碼 $exitCode)。請檢查上方輸出的錯誤訊息 (常見原因: 443 埠已被占用、找不到映像檔)。"
        }
    }
    Write-Ok '容器已啟動 (docker compose up -d 完成)。'

    Write-Info '等待容器健康檢查通過 (https://localhost/api/health，最多 90 秒)...'
    $healthResult = Wait-ForHealthCheck

    if (-not $healthResult.Reachable) {
        Write-Fail "容器啟動後，在等待時間內無法連線至 https://localhost/api/health。請執行 'docker compose logs sqlcheck' 檢查容器記錄。"
        return $false
    }
    Write-Ok "健康檢查回應 200 OK (status=$($healthResult.Status))。"

    if ($healthResult.AiAvailable) {
        Write-Ok 'ai_available: true - AI 輔助複核功能可正常連線至 Ollama。'
    } else {
        Write-Warn 'ai_available: false - 容器已正常啟動，但目前無法連線至 Ollama (AI 輔助複核暫不可用)。決定性規則檢查仍可正常運作，不因此判定部署失敗。請檢查 OLLAMA_HOST 設定、Ollama 是否已重新啟動、以及防火牆規則 (11434)。'
    }

    Write-Info '執行 smoke test (.\smoke-test.ps1)...'
    $smokeTestScript = Join-Path $script:DeployRoot 'smoke-test.ps1'
    & $smokeTestScript -BaseUrl 'https://localhost'
    $smokeExit = $LASTEXITCODE

    if ($smokeExit -eq 0) {
        Write-Ok 'Smoke test 全數通過。'
    } else {
        Write-Fail "Smoke test 未全數通過 (結束碼 $smokeExit)。請參考上方輸出排查問題。"
    }

    $url = "https://$ProductionIp/"
    if ($smokeExit -eq 0) {
        Write-Info "開啟瀏覽器: $url"
        try {
            Start-Process $url | Out-Null
        } catch {
            Write-Warn "無法自動開啟瀏覽器: $($_.Exception.Message)。請手動開啟 $url"
        }
    } else {
        Write-Info "略過自動開啟瀏覽器 (smoke test 未通過)。可手動開啟 $url 進一步檢查。"
    }

    return ($smokeExit -eq 0)
}

# ============================================================================
# -Rollback
# ============================================================================
function Invoke-Rollback {
    Write-Step 'Rollback: 回復至前一版映像檔'

    Write-Info '停止目前容器 (docker compose down)...'
    $downExit = Invoke-DockerCompose down
    if ($downExit -ne 0) {
        Write-Warn "docker compose down 回傳非 0 結束碼 ($downExit)，仍繼續嘗試回復。"
    }

    docker image inspect sqlcheck-app:prev *> $null
    $prevImageExists = ($LASTEXITCODE -eq 0)
    if (-not $prevImageExists) {
        Write-Fail '找不到復原點映像檔 sqlcheck-app:prev，無法回復。此映像檔只有在先前執行過一次成功的部署 (未使用 -SkipBuild) 後才會存在。'
        return $false
    }

    Write-Info '將 sqlcheck-app:prev 重新標記為 sqlcheck-app:latest...'
    docker tag sqlcheck-app:prev sqlcheck-app:latest
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "docker tag 失敗 (結束碼 $LASTEXITCODE)。"
        return $false
    }

    Write-Info '重新啟動容器 (docker compose up -d)...'
    $upExit = Invoke-DockerCompose up -d
    if ($upExit -ne 0) {
        Write-Fail "docker compose up -d 失敗 (結束碼 $upExit)。"
        return $false
    }

    Write-Ok '已回復至前一版映像檔並重新啟動容器。'
    return $true
}

# ============================================================================
# -Down
# ============================================================================
function Invoke-Down {
    Write-Step 'Down: 停止並移除容器'

    $exitCode = Invoke-DockerCompose down
    if ($exitCode -ne 0) {
        Write-Fail "docker compose down 失敗 (結束碼 $exitCode)。"
        return $false
    }

    Write-Ok '容器已停止並移除 (docker compose down 完成)。'
    return $true
}

# ============================================================================
# Main
# ============================================================================
if (-not (Test-Path $script:LogsDir)) {
    New-Item -ItemType Directory -Path $script:LogsDir -Force | Out-Null
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$transcriptPath = Join-Path $script:LogsDir "deploy-$timestamp.log"
$transcriptStarted = $false
try {
    Start-Transcript -Path $transcriptPath -ErrorAction Stop | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host "[WARN] 無法建立紀錄檔 $transcriptPath : $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ''
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host '  SQLCheck 2.0 - 正式主機一鍵部署 (Phase 7)' -ForegroundColor Cyan
Write-Host '======================================================' -ForegroundColor Cyan
Write-Info "紀錄檔: $transcriptPath"
Write-Info "參數: ProductionIp=$ProductionIp OllamaModel=$OllamaModel CheckOnly=$($CheckOnly.IsPresent) SkipBuild=$($SkipBuild.IsPresent) Rollback=$($Rollback.IsPresent) Down=$($Down.IsPresent)"

$overallSuccess = $true

try {
    if ($Down) {
        $overallSuccess = Invoke-Down
    }
    elseif ($Rollback) {
        $overallSuccess = Invoke-Rollback
    }
    else {
        $preflightResults = Invoke-Preflight
        $preflightPassed = -not ($preflightResults.Values -contains $false)

        if ($CheckOnly) {
            Write-Step 'Preflight 檢查總結 (-CheckOnly：僅檢查，未執行任何變更)'
            foreach ($key in $preflightResults.Keys) {
                if ($preflightResults[$key]) {
                    Write-Host ("  [PASS] {0}" -f $key) -ForegroundColor Green
                } else {
                    Write-Host ("  [FAIL] {0}" -f $key) -ForegroundColor Red
                }
            }
            $overallSuccess = $preflightPassed
        }
        elseif (-not $preflightPassed) {
            Write-Host ''
            Write-Fail 'Preflight 檢查未全數通過，部署中止。請解決上方列出的問題後再重新執行本腳本。'
            $overallSuccess = $false
        }
        else {
            Set-OllamaHostBinding
            Set-FirewallRules
            Initialize-EnvFile
            Initialize-TlsCertificate
            $overallSuccess = Invoke-BuildAndStart
        }
    }
}
catch {
    Write-Host ''
    Write-Fail "部署過程發生未預期的錯誤: $($_.Exception.Message)"
    Write-Info "完整記錄請參考: $transcriptPath"
    $overallSuccess = $false
}
finally {
    Write-Host ''
    if ($overallSuccess) {
        Write-Host '======================================================' -ForegroundColor Green
        Write-Host '  完成 (SUCCESS)' -ForegroundColor Green
        Write-Host '======================================================' -ForegroundColor Green
    } else {
        Write-Host '======================================================' -ForegroundColor Red
        Write-Host '  未完全成功 (FAILURE) - 請參考上方訊息與紀錄檔' -ForegroundColor Red
        Write-Host '======================================================' -ForegroundColor Red
    }
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if ($overallSuccess) { exit 0 } else { exit 1 }
