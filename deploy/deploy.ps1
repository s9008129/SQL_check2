#Requires -Version 7.0
<#
.SYNOPSIS
    SQLCheck 2.0 - 正式主機 App-only 一鍵部署。

.DESCRIPTION
    只處理 SQLCheck 應用程式部署，不修改 Windows Firewall、OLLAMA_HOST、
    Ollama process 或 Windows 網路設定。

    流程：
      1. Preflight
      2. Git clean + ff-only 更新
      3. 保留/準備 .env
      4. 以目前執行中的 image 建立 sqlcheck-app:prev rollback 點
      5. build sqlcheck image
      6. 確認/產生 TLS cert
      7. 只重建 sqlcheck service，執行 health + smoke test
      8. 核心驗證失敗時自動 rollback

    需要處理 11434 / Windows Firewall / OLLAMA_HOST 時，請另行使用
    deploy-infra.ps1；不要把基礎設施設定混入日常應用程式部署。

.PARAMETER CheckOnly
    只做唯讀檢查，不 git pull、不修改 .env、不 build、不重建 container。

.PARAMETER SkipPull
    不執行 git fetch / git pull。

.PARAMETER SkipBuild
    不 build，使用現有 sqlcheck-app:latest。

.PARAMETER Rollback
    使用 sqlcheck-app:prev 回復並重建 sqlcheck service。

.PARAMETER Down
    執行 docker compose down。

.PARAMETER Branch
    正式部署 branch，預設 main。

.PARAMETER ExpectedCommit
    選填。git 更新後 HEAD 必須符合此 SHA 或 SHA prefix。

.PARAMETER RepoRoot
    選填。預設由本腳本所在 deploy 目錄往上一層推導。

.PARAMETER ProductionIp
    首次產生 TLS cert 的 SAN 與完成訊息網址。預設 10.97.15.58。

.PARAMETER OllamaModel
    只有在 .env 不存在、由 .env.example 建立時才套用。既有 .env 不覆寫。

.PARAMETER KnowledgeContextMode
    keep：不改既有 .env（預設）
    on：SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED=true
    off：SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED=false

.PARAMETER MigrateLegacyNumCtx
    既有 .env 若仍為 OLLAMA_NUM_CTX=8192，先備份再更新為 16384。

.PARAMETER RequireAi
    若 /api/health 的 ai_available 不是 true，視為部署失敗並觸發 rollback。
    預設不指定時只警告，決定性規則仍可用。

.PARAMETER NoAutoRollback
    驗證失敗時不自動 rollback，保留失敗版本供人工排查。
#>

[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipPull,
    [switch]$SkipBuild,
    [switch]$Rollback,
    [switch]$Down,
    [switch]$MigrateLegacyNumCtx,
    [switch]$RequireAi,
    [switch]$NoAutoRollback,
    [string]$Branch = 'main',
    [string]$ExpectedCommit = '',
    [string]$RepoRoot = '',
    [string]$ProductionIp = '10.97.15.58',
    [string]$OllamaModel = 'gemma4:31b',
    [ValidateSet('keep', 'on', 'off')]
    [string]$KnowledgeContextMode = 'keep'
)

$ErrorActionPreference = 'Stop'
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $candidateRoot = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $candidateRoot 'docker-compose.yml'))) {
        throw '無法由腳本位置推導 repository root。請指定 -RepoRoot D:\dev\SQL_check2。'
    }
    $script:RepoRoot = (Resolve-Path $candidateRoot).Path
} else {
    if (-not (Test-Path $RepoRoot)) {
        throw "RepoRoot 不存在：$RepoRoot"
    }
    $script:RepoRoot = (Resolve-Path $RepoRoot).Path
}

$script:DeployRoot    = Join-Path $script:RepoRoot 'deploy'
$script:LogsDir       = Join-Path $script:DeployRoot 'logs'
$script:CertsDir      = Join-Path $script:RepoRoot 'certs'
$script:DataDir       = Join-Path $script:RepoRoot 'data'
$script:EnvFile       = Join-Path $script:RepoRoot '.env'
$script:EnvExample    = Join-Path $script:RepoRoot '.env.example'
$script:ComposeFile   = Join-Path $script:RepoRoot 'docker-compose.yml'
$script:SmokeTest     = Join-Path $script:DeployRoot 'smoke-test.ps1'
$script:Service       = 'sqlcheck'
$script:ContainerName = 'sqlcheck-app'
$script:ImageLatest   = 'sqlcheck-app:latest'
$script:ImagePrevious = 'sqlcheck-app:prev'

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}
function Write-Info { param([string]$Message) Write-Host "  [INFO] $Message" -ForegroundColor Gray }
function Write-Ok   { param([string]$Message) Write-Host "  [ OK ] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "  [FAIL] $Message" -ForegroundColor Red }

function Stop-Deploy {
    param([string]$Message)
    Write-Fail $Message
    throw $Message
}

function Invoke-DockerCompose {
    Push-Location $script:RepoRoot
    try {
        & docker compose @args | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    return $code
}

function Invoke-GitVisible {
    Push-Location $script:RepoRoot
    try {
        & git @args | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    return $code
}

function Get-GitOutput {
    param([string[]]$Arguments)

    Push-Location $script:RepoRoot
    try {
        $output = & git @Arguments 2>$null
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($code -ne 0) {
        throw "git $($Arguments -join ' ') 失敗（exit=$code）。"
    }
    return @($output)
}

function Test-CommandAvailable {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-DockerReady {
    if (-not (Test-CommandAvailable 'docker')) { return $false }
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Test-ImageExists {
    param([string]$Image)
    & docker image inspect $Image *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-EnvValue {
    param([string]$Path, [string]$Name)

    if (-not (Test-Path $Path)) { return $null }
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)\s*$'
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match $pattern) {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Backup-File {
    param([string]$Path)

    $backup = "$Path.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -Path $Path -Destination $backup -Force
    return $backup
}

function Set-EnvValue {
    param([string]$Path, [string]$Name, [string]$Value)

    if (-not (Test-Path $Path)) {
        throw "找不到 .env：$Path"
    }

    $content = Get-Content -Path $Path -Raw
    $pattern = '(?m)^\s*' + [regex]::Escape($Name) + '\s*=.*$'
    $line = "$Name=$Value"

    if ([regex]::IsMatch($content, $pattern)) {
        $updated = [regex]::Replace($content, $pattern, $line)
    } else {
        $newline = [Environment]::NewLine
        $separator = if ($content.EndsWith($newline)) { '' } else { $newline }
        $updated = $content + $separator + $line + $newline
    }

    Set-Content -Path $Path -Value $updated -Encoding utf8NoBOM
}

function Show-RecentContainerLogs {
    Write-Info '最近 120 行 sqlcheck logs：'
    $code = Invoke-DockerCompose logs --tail=120 $script:Service
    if ($code -ne 0) {
        Write-Warn "無法取得 container logs（exit=$code）。"
    }
}

function Test-DataDirWritable {
    if (-not (Test-Path $script:DataDir)) {
        try {
            New-Item -ItemType Directory -Path $script:DataDir -Force | Out-Null
        } catch {
            return $false
        }
    }

    $probe = Join-Path $script:DataDir '.write-probe'
    try {
        Set-Content -Path $probe -Value 'ok' -Encoding utf8 -ErrorAction Stop
        Remove-Item -Path $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Invoke-Preflight {
    Write-Step 'Step 1/7: Preflight'

    foreach ($path in @(
        $script:ComposeFile,
        (Join-Path $script:RepoRoot 'Dockerfile'),
        $script:EnvExample,
        $script:SmokeTest
    )) {
        if (-not (Test-Path $path)) {
            Stop-Deploy "缺少必要檔案：$path"
        }
    }
    Write-Ok '必要專案檔案存在。'

    if (-not (Test-CommandAvailable 'git')) {
        Stop-Deploy '找不到 git CLI。'
    }
    Write-Ok 'git CLI 可用。'

    if (-not (Test-DockerReady)) {
        Stop-Deploy 'Docker Desktop 尚未就緒（docker info 失敗）。請先啟動 Docker Desktop。'
    }
    Write-Ok 'Docker Desktop 引擎正常。'

    $composeCode = Invoke-DockerCompose config --quiet
    if ($composeCode -ne 0) {
        Stop-Deploy "docker compose config 驗證失敗（exit=$composeCode）。"
    }
    Write-Ok 'docker-compose.yml 驗證通過。'

    $inside = (Get-GitOutput @('rev-parse', '--is-inside-work-tree') | Select-Object -First 1)
    if ($inside -ne 'true') {
        Stop-Deploy "$script:RepoRoot 不是 Git working tree。"
    }

    $currentBranch = (Get-GitOutput @('branch', '--show-current') | Select-Object -First 1)
    if ($currentBranch -ne $Branch) {
        Stop-Deploy "目前 branch 是 '$currentBranch'，正式部署要求 '$Branch'。"
    }
    Write-Ok "目前 branch：$currentBranch"

    $dirty = @(Get-GitOutput @('status', '--porcelain'))
    if ($dirty.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace(($dirty -join ''))) {
        Write-Fail 'working tree 不是乾淨狀態。腳本不會 stash/reset/覆蓋正式主機本地修改。'
        $dirty | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
        throw 'Git working tree dirty.'
    }
    Write-Ok 'Git working tree 乾淨。'

    if (Test-Path $script:EnvFile) {
        Write-Ok '.env 已存在；App-only deploy 不會整份覆寫。'
    } else {
        Write-Warn '.env 尚不存在；正式部署時會從 .env.example 建立。'
    }

    $crt = Join-Path $script:CertsDir 'sqlcheck.crt'
    $key = Join-Path $script:CertsDir 'sqlcheck.key'
    if ((Test-Path $crt) -and (Test-Path $key)) {
        Write-Ok 'TLS cert/key 已存在。'
    } else {
        Write-Warn 'TLS cert/key 尚未完整存在；正式部署時會以 app image 產生。'
    }

    $ollamaHost = [System.Environment]::GetEnvironmentVariable('OLLAMA_HOST', 'User')
    if ([string]::IsNullOrWhiteSpace($ollamaHost)) {
        Write-Warn 'OLLAMA_HOST(User) 未設定。本腳本只顯示狀態，不會修改。'
    } else {
        Write-Info "OLLAMA_HOST(User)=$ollamaHost（唯讀，不修改）"
    }

    try {
        $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 -ErrorAction Stop
        $names = @($tags.models | ForEach-Object { $_.name })
        Write-Ok "主機本機 Ollama API 可連線。模型：$($names -join ', ')"
    } catch {
        Write-Warn "主機本機 Ollama API 目前無法連線：$($_.Exception.Message)"
        Write-Warn '本腳本不會修改 Firewall / OLLAMA_HOST；container 啟動後由 /api/health 再判斷。'
    }
}

function Update-Repository {
    Write-Step 'Step 2/7: Git 安全更新'

    if ($SkipPull) {
        Write-Info '已指定 -SkipPull，略過 fetch/pull。'
    } else {
        Write-Info 'git fetch origin --prune'
        if ((Invoke-GitVisible fetch origin --prune) -ne 0) {
            Stop-Deploy 'git fetch 失敗。'
        }

        Write-Info "git pull --ff-only origin $Branch"
        if ((Invoke-GitVisible pull --ff-only origin $Branch) -ne 0) {
            Stop-Deploy 'git pull --ff-only 失敗；腳本不會自動 merge/rebase。'
        }
    }

    $head = (Get-GitOutput @('rev-parse', 'HEAD') | Select-Object -First 1)
    Write-Ok "HEAD=$head"

    if (-not [string]::IsNullOrWhiteSpace($ExpectedCommit)) {
        if (-not $head.StartsWith($ExpectedCommit, [System.StringComparison]::OrdinalIgnoreCase)) {
            Stop-Deploy "HEAD=$head，不符合 ExpectedCommit=$ExpectedCommit。"
        }
        Write-Ok "HEAD 符合 ExpectedCommit=$ExpectedCommit"
    }
}

function Initialize-Environment {
    Write-Step 'Step 3/7: .env / Runtime mode'

    if (-not (Test-Path $script:EnvFile)) {
        Copy-Item -Path $script:EnvExample -Destination $script:EnvFile -Force
        $content = Get-Content -Path $script:EnvFile -Raw
        $content = [regex]::Replace($content, '(?m)^OLLAMA_MODEL=.*$', "OLLAMA_MODEL=$OllamaModel")
        Set-Content -Path $script:EnvFile -Value $content -Encoding utf8NoBOM
        Write-Ok ".env 已由 .env.example 建立（OLLAMA_MODEL=$OllamaModel）。"
    } else {
        Write-Ok '.env 已存在，保留既有值。'
    }

    $ctx = Get-EnvValue -Path $script:EnvFile -Name 'OLLAMA_NUM_CTX'
    if ($ctx -eq '8192') {
        if ($MigrateLegacyNumCtx) {
            $backup = Backup-File -Path $script:EnvFile
            Set-EnvValue -Path $script:EnvFile -Name 'OLLAMA_NUM_CTX' -Value '16384'
            Write-Ok "OLLAMA_NUM_CTX 8192 -> 16384；備份：$backup"
        } else {
            Write-Warn '偵測到 OLLAMA_NUM_CTX=8192；目前建議值為 16384。'
            Write-Warn '本次不自動修改；要遷移請加 -MigrateLegacyNumCtx。'
        }
    }

    if ($KnowledgeContextMode -ne 'keep') {
        $desired = if ($KnowledgeContextMode -eq 'on') { 'true' } else { 'false' }
        $current = Get-EnvValue -Path $script:EnvFile -Name 'SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED'
        if ($current -ne $desired) {
            $backup = Backup-File -Path $script:EnvFile
            Set-EnvValue -Path $script:EnvFile -Name 'SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED' -Value $desired
            Write-Ok "Compact Context=$desired；原 .env 備份：$backup"
        } else {
            Write-Ok "Compact Context 已是 $desired。"
        }
    } else {
        $current = Get-EnvValue -Path $script:EnvFile -Name 'SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED'
        if ($null -eq $current) {
            Write-Info 'Compact Context 未寫在 .env；Runtime 預設 true。'
        } else {
            Write-Info "Compact Context=$current"
        }
    }

    if (Test-DataDirWritable) {
        Write-Ok "data directory 可寫入：$script:DataDir"
    } else {
        Write-Warn "data directory 無法寫入：$script:DataDir"
        Write-Warn 'SQL archive 可能無法落盤，但不阻擋 SQL 檢核。'
    }
}

function Save-RollbackPoint {
    Write-Step 'Step 4/7: 建立 rollback point'

    $runningImageId = $null
    & docker inspect $script:ContainerName --format '{{.Image}}' *> $null
    if ($LASTEXITCODE -eq 0) {
        $runningImageId = (& docker inspect $script:ContainerName --format '{{.Image}}' 2>$null | Select-Object -First 1)
    }

    if (-not [string]::IsNullOrWhiteSpace($runningImageId)) {
        & docker tag $runningImageId $script:ImagePrevious
        if ($LASTEXITCODE -ne 0) {
            Stop-Deploy "無法把目前執行中的 image 標記成 $script:ImagePrevious。"
        }
        Write-Ok "Rollback point=$script:ImagePrevious（from running container）"
        return
    }

    if (Test-ImageExists $script:ImageLatest) {
        & docker tag $script:ImageLatest $script:ImagePrevious
        if ($LASTEXITCODE -ne 0) {
            Stop-Deploy "無法建立 $script:ImagePrevious。"
        }
        Write-Ok "Rollback point=$script:ImagePrevious（from latest）"
        return
    }

    Write-Warn '首次部署：找不到既有 image，沒有 rollback point。'
}

function Build-Application {
    Write-Step 'Step 5/7: Build'

    if ($SkipBuild) {
        if (-not (Test-ImageExists $script:ImageLatest)) {
            Stop-Deploy '-SkipBuild 已指定，但找不到 sqlcheck-app:latest。'
        }
        Write-Info '使用既有 sqlcheck-app:latest。'
        return
    }

    $code = Invoke-DockerCompose build $script:Service
    if ($code -ne 0) {
        Stop-Deploy "docker compose build 失敗（exit=$code）。目前正式 container 尚未被重建。"
    }
    Write-Ok 'SQLCheck image build 完成。'
}

function Ensure-TlsCertificate {
    Write-Step 'Step 6/7: TLS'

    $crt = Join-Path $script:CertsDir 'sqlcheck.crt'
    $key = Join-Path $script:CertsDir 'sqlcheck.key'
    $cer = Join-Path $script:CertsDir 'sqlcheck.cer'

    if ((Test-Path $crt) -and (Test-Path $key) -and
        ((Get-Item $crt).Length -gt 0) -and ((Get-Item $key).Length -gt 0)) {
        Write-Ok '既有 TLS cert/key 完整，保留不動。'
        return
    }

    if (-not (Test-ImageExists $script:ImageLatest)) {
        Stop-Deploy '找不到 sqlcheck-app:latest，無法產生 TLS cert。'
    }

    if (-not (Test-Path $script:CertsDir)) {
        New-Item -ItemType Directory -Path $script:CertsDir -Force | Out-Null
    }

    Write-Warn 'TLS cert/key 不完整，使用目前 image 產生。'
    $mount = "$($script:CertsDir):/certs"
    $certArgs = @(
        'run', '--rm',
        '-v', $mount,
        $script:ImageLatest,
        'python', '-m', 'app.certgen',
        '--out-dir', '/certs',
        '--host', $ProductionIp,
        '--host', $env:COMPUTERNAME
    )
    & docker @certArgs | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Stop-Deploy "TLS certgen 失敗（exit=$LASTEXITCODE）。"
    }

    if (-not ((Test-Path $crt) -and (Test-Path $key))) {
        Stop-Deploy 'certgen 完成，但 sqlcheck.crt/sqlcheck.key 不完整。'
    }

    Write-Ok 'TLS cert/key 已產生。'
    if (Test-Path $cer) {
        Write-Info 'sqlcheck.cer 已產生。本 App-only 腳本不修改 Windows Trusted Root。'
    }
}

function Wait-ForHealth {
    param([int]$MaxWaitSeconds = 90, [int]$IntervalSeconds = 3)

    $elapsed = 0
    while ($elapsed -lt $MaxWaitSeconds) {
        try {
            $body = Invoke-RestMethod -Uri 'https://localhost/api/health' -SkipCertificateCheck -TimeoutSec 5 -ErrorAction Stop
            if ($body.status -eq 'ok') {
                return @{ Success = $true; Body = $body }
            }
        } catch {
        }

        Start-Sleep -Seconds $IntervalSeconds
        $elapsed += $IntervalSeconds
        Write-Info "等待 /api/health... $elapsed / $MaxWaitSeconds 秒"
    }

    return @{ Success = $false; Body = $null }
}

function Invoke-CoreValidation {
    Write-Step 'Step 7/7: Recreate + Health + Smoke'

    $code = Invoke-DockerCompose up -d --no-deps --force-recreate $script:Service
    if ($code -ne 0) {
        return @{ Success = $false; Reason = "docker compose up 失敗（exit=$code）" }
    }

    Write-Ok 'sqlcheck service 已重建。'

    $health = Wait-ForHealth
    if (-not $health.Success) {
        return @{ Success = $false; Reason = '/api/health 在 90 秒內未成功' }
    }

    Write-Ok '/api/health status=ok'

    if ([bool]$health.Body.ai_available) {
        Write-Ok 'ai_available=true（container -> Ollama 正常）'
    } else {
        if ($RequireAi) {
            return @{ Success = $false; Reason = 'ai_available=false 且指定了 -RequireAi' }
        }
        Write-Warn 'ai_available=false；決定性規則仍可運作。'
        Write-Warn 'App-only deploy 不會修改 Firewall / OLLAMA_HOST。'
    }

    & $script:SmokeTest -BaseUrl 'https://localhost' | Out-Host
    $smokeCode = $LASTEXITCODE
    if ($smokeCode -ne 0) {
        return @{ Success = $false; Reason = "smoke-test.ps1 失敗（exit=$smokeCode）" }
    }

    Write-Ok 'Smoke test 全數通過。'
    return @{ Success = $true; Reason = ''; Health = $health.Body }
}

function Invoke-RollbackImage {
    Write-Step 'Rollback: sqlcheck-app:prev'

    if (-not (Test-ImageExists $script:ImagePrevious)) {
        Write-Fail "找不到 $script:ImagePrevious。"
        return $false
    }

    & docker tag $script:ImagePrevious $script:ImageLatest
    if ($LASTEXITCODE -ne 0) {
        Write-Fail 'docker tag rollback image 失敗。'
        return $false
    }

    $code = Invoke-DockerCompose up -d --no-deps --force-recreate $script:Service
    if ($code -ne 0) {
        Write-Fail "rollback recreate 失敗（exit=$code）。"
        return $false
    }

    $health = Wait-ForHealth
    if (-not $health.Success) {
        Write-Fail 'rollback image 已啟動，但 /api/health 未恢復。'
        Show-RecentContainerLogs
        return $false
    }

    Write-Ok 'Rollback 完成，/api/health 已恢復。'
    return $true
}

function Show-CheckSummary {
    Write-Step 'CheckOnly summary'

    $head = (Get-GitOutput @('rev-parse', 'HEAD') | Select-Object -First 1)
    Write-Info "HEAD=$head"

    $ctx = Get-EnvValue -Path $script:EnvFile -Name 'SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED'
    if ($null -eq $ctx) { $ctx = 'true (runtime default)' }
    Write-Info "Compact Context=$ctx"

    if (Test-ImageExists $script:ImageLatest) {
        Write-Ok "$script:ImageLatest 存在。"
    } else {
        Write-Warn "$script:ImageLatest 不存在（首次部署時正常）。"
    }

    Write-Ok 'CheckOnly 完成：沒有修改 Git、.env、container、Firewall、OLLAMA_HOST 或 Ollama。'
}

if (-not (Test-Path $script:LogsDir)) {
    New-Item -ItemType Directory -Path $script:LogsDir -Force | Out-Null
}

$transcriptPath = Join-Path $script:LogsDir ("deploy-app-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:TranscriptStarted = $false

try {
    Start-Transcript -Path $transcriptPath -ErrorAction Stop | Out-Null
    $script:TranscriptStarted = $true
} catch {
    Write-Warn "無法啟動 transcript：$($_.Exception.Message)"
}

function Invoke-Main {
    try {
        Write-Host ''
        Write-Host '============================================================' -ForegroundColor Cyan
        Write-Host ' SQLCheck 2.0 - App-only Deployment' -ForegroundColor Cyan
        Write-Host ' 不修改 Firewall / OLLAMA_HOST / Ollama process' -ForegroundColor Yellow
        Write-Host '============================================================' -ForegroundColor Cyan
        Write-Info "Repo=$script:RepoRoot"
        Write-Info "Log =$transcriptPath"

        if ($Down) {
            Write-Step 'Down'
            $code = Invoke-DockerCompose down
            if ($code -ne 0) {
                Stop-Deploy "docker compose down 失敗（exit=$code）。"
            }
            Write-Ok 'container 已停止並移除。'
            return 0
        }

        if ($Rollback) {
            if (Invoke-RollbackImage) { return 0 }
            return 1
        }

        Invoke-Preflight

        if ($CheckOnly) {
            Show-CheckSummary
            return 0
        }

        Update-Repository
        Initialize-Environment
        Save-RollbackPoint
        Build-Application
        Ensure-TlsCertificate

        $validation = Invoke-CoreValidation
        if (-not $validation.Success) {
            Write-Fail "新版部署驗證失敗：$($validation.Reason)"
            Show-RecentContainerLogs

            if (-not $NoAutoRollback) {
                Write-Warn '開始自動 rollback...'
                if (Invoke-RollbackImage) {
                    Write-Warn '已回復上一版；請依 logs 排查新版問題。'
                } else {
                    Write-Fail '自動 rollback 失敗，需要人工處理。'
                }
            } else {
                Write-Warn '已指定 -NoAutoRollback；保留目前版本供人工排查。'
            }
            return 1
        }

        $head = (Get-GitOutput @('rev-parse', 'HEAD') | Select-Object -First 1)
        $ctx = Get-EnvValue -Path $script:EnvFile -Name 'SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED'
        if ($null -eq $ctx) { $ctx = 'true (runtime default)' }

        Write-Host ''
        Write-Host '============================================================' -ForegroundColor Green
        Write-Host ' SQLCheck App-only 部署完成' -ForegroundColor Green
        Write-Host '============================================================' -ForegroundColor Green
        Write-Ok "HEAD=$head"
        Write-Ok 'health + smoke test 通過。'
        Write-Info "Compact Context=$ctx"
        Write-Info "正式網址=https://$ProductionIp/"
        Write-Info '本次未修改 Windows Firewall / OLLAMA_HOST / Ollama process。'
        return 0
    } catch {
        Write-Fail $_.Exception.Message
        return 1
    }
}

$exitCode = 1
try {
    $exitCode = Invoke-Main
} finally {
    if ($script:TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}

exit $exitCode
