param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = 'Stop'

$deployPath = Join-Path $RepoRoot 'deploy/deploy.ps1'
$infraPath = Join-Path $RepoRoot 'deploy/deploy-infra.ps1'

if (-not (Test-Path $deployPath)) { throw "Missing $deployPath" }
if (-not (Test-Path $infraPath)) { throw "Missing $infraPath" }

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $deployPath,
    [ref]$tokens,
    [ref]$errors
)

if ($errors.Count -gt 0) {
    $messages = $errors | ForEach-Object { $_.Message }
    throw "deploy.ps1 parse errors: $($messages -join ' | ')"
}

$text = Get-Content -Path $deployPath -Raw

$forbidden = @(
    'New-NetFirewallRule',
    'Set-NetFirewallRule',
    'Remove-NetFirewallRule',
    'Get-NetFirewallRule',
    'BreakGlassFirewall',
    'DockerRemoteAddress',
    "SetEnvironmentVariable('OLLAMA_HOST'",
    'Stop-Process -Force',
    'certutil -addstore'
)

foreach ($needle in $forbidden) {
    if ($text.Contains($needle)) {
        throw "App-only deploy must not contain infra mutation token: $needle"
    }
}

$required = @(
    'pull --ff-only',
    'sqlcheck-app:prev',
    '--no-deps',
    '--force-recreate',
    'KnowledgeContextMode',
    'MigrateLegacyNumCtx',
    'NoAutoRollback',
    'Restore-EnvironmentForRun',
    'docker inspect $script:ContainerName',
    'smoke-test.ps1',
    'api/health'
)

foreach ($needle in $required) {
    if (-not $text.Contains($needle)) {
        throw "App-only deploy is missing required safety token: $needle"
    }
}

Write-Host 'APP-ONLY DEPLOY POLICY CHECKS PASSED'
