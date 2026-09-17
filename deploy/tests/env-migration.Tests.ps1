#Requires -Version 7.0
<#
.SYNOPSIS
    Behavioural tests for the legacy `.env` migration helper in deploy.ps1.

.DESCRIPTION
    2026-09-17: `.env.example` shipped `OLLAMA_NUM_CTX=8192` while app.yaml's
    `num_ctx_default` is 16384. 8192 is below the real system prompt plus the
    3072-token output budget, so Ollama silently truncates the prompt. deploy.ps1
    must therefore *detect* an existing `.env` that still carries the old value,
    explain the consequence, and rewrite **only that line** after the operator
    confirms - never overwrite the rest of the file, and never change anything
    when the answer is no.

    The tests parse deploy.ps1 with the PowerShell AST and dot-source only the
    two helper functions under test; deploy.ps1 itself is never executed, so
    nothing is deployed and no `.env` outside the temp directory is touched.

.EXAMPLE
    # From the repository root (PowerShell 7 on any OS):
    pwsh -NoProfile -File deploy/tests/env-migration.Tests.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:Failures = 0
$script:Checks = 0

$deployScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'deploy.ps1'
if (-not (Test-Path $deployScript)) {
    Write-Host "找不到 deploy.ps1: $deployScript" -ForegroundColor Red
    exit 2
}

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($deployScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {
    Write-Host 'deploy.ps1 有語法錯誤，無法測試：' -ForegroundColor Red
    foreach ($e in $parseErrors) {
        Write-Host ("  line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message)
    }
    exit 2
}

$wanted = @('Test-LegacyNumCtx', 'Repair-LegacyNumCtx')
$source = [System.Text.StringBuilder]::new()
foreach ($f in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $f.Name) { [void]$source.AppendLine($f.Extent.Text) }
}
. ([scriptblock]::Create($source.ToString()))

Set-Item -Path function:Write-Ok -Value { param([string]$Message) $script:LastOk = $Message }
Set-Item -Path function:Write-Warn -Value { param([string]$Message) $script:LastWarn = $Message }
Set-Item -Path function:Write-Info -Value { param([string]$Message) $script:LastInfo = $Message }
Set-Item -Path function:Write-Fail -Value { param([string]$Message) $script:LastFail = $Message }

function Assert-True {
    param([string]$Name, [bool]$Actual, [bool]$Expected = $true)
    $script:Checks++
    if ($Actual -eq $Expected) { Write-Host "  PASS  $Name" }
    else {
        $script:Failures++
        Write-Host "  FAIL  $Name (expected $Expected, got $Actual)" -ForegroundColor Red
    }
}

function Assert-Equal {
    param([string]$Name, [object]$Actual, [object]$Expected)
    $script:Checks++
    $a = if ($null -eq $Actual) { '<null>' } else { [string]$Actual }
    $e = if ($null -eq $Expected) { '<null>' } else { [string]$Expected }
    if ($a -eq $e) { Write-Host "  PASS  $Name" }
    else {
        $script:Failures++
        Write-Host "  FAIL  $Name (expected '$e', got '$a')" -ForegroundColor Red
    }
}

# Read-Host is a cmdlet; a function of the same name wins command resolution,
# so the operator's answer can be simulated without any interaction.
$script:Answer = 'n'
function Read-Host { param([string]$Prompt) if ($Prompt) { $script:LastPrompt = $Prompt }; return $script:Answer }

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sqlcheck-env-migration-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

try {
    Write-Host '== Test-LegacyNumCtx =='
    $missing = Join-Path $tmpDir 'nope.env'
    Assert-True 'missing file is not legacy' (Test-LegacyNumCtx -Path $missing) $false

    $newEnv = Join-Path $tmpDir 'new.env'
    Set-Content -Path $newEnv -Value "OLLAMA_NUM_CTX=16384`nOLLAMA_MODEL=gemma4:31b`n"
    Assert-True '16384 is not legacy' (Test-LegacyNumCtx -Path $newEnv) $false

    $oldEnv = Join-Path $tmpDir 'old.env'
    Set-Content -Path $oldEnv -Value "OLLAMA_BASE_URL=http://host.docker.internal:11434`nOLLAMA_NUM_CTX=8192`nOLLAMA_MODEL=gemma4:31b`n"
    Assert-True '8192 is legacy' (Test-LegacyNumCtx -Path $oldEnv) $true

    $spacedEnv = Join-Path $tmpDir 'spaced.env'
    Set-Content -Path $spacedEnv -Value "OLLAMA_NUM_CTX = 8192 `n"
    Assert-True 'whitespace around = is still legacy' (Test-LegacyNumCtx -Path $spacedEnv) $true

    $commentedEnv = Join-Path $tmpDir 'commented.env'
    Set-Content -Path $commentedEnv -Value "# OLLAMA_NUM_CTX=8192`nOLLAMA_NUM_CTX=16384`n"
    Assert-True 'commented-out 8192 is not legacy' (Test-LegacyNumCtx -Path $commentedEnv) $false

    $similarEnv = Join-Path $tmpDir 'similar.env'
    Set-Content -Path $similarEnv -Value "OLLAMA_NUM_CTX=81920`n"
    Assert-True '81920 is not 8192' (Test-LegacyNumCtx -Path $similarEnv) $false

    Write-Host '== Repair-LegacyNumCtx (declined) =='
    $declineEnv = Join-Path $tmpDir 'decline.env'
    Set-Content -Path $declineEnv -Value "OLLAMA_NUM_CTX=8192`nOTHER_SETTING=keep-me"
    # Read the file back as the baseline: Set-Content appends a trailing newline,
    # and the assertions below are about "the bytes did not change", not about
    # what that trailing newline happens to be.
    $original = Get-Content -Path $declineEnv -Raw
    $script:Answer = 'n'
    Repair-LegacyNumCtx -Path $declineEnv
    Assert-Equal 'file unchanged when declined' (Get-Content -Path $declineEnv -Raw) $original
    Assert-True 'declined run warned' ([bool]$script:LastWarn) $true
    Assert-True 'declined run created no backup' ([bool](Get-ChildItem -Path $tmpDir -Filter 'decline.env.bak-*')) $false
    Assert-True 'declined run still asked the operator' ([bool]$script:LastPrompt) $true

    Write-Host '== Repair-LegacyNumCtx (confirmed) =='
    $script:Answer = 'y'
    Repair-LegacyNumCtx -Path $declineEnv
    $after = Get-Content -Path $declineEnv -Raw
    Assert-True 'line rewritten to 16384' ($after -match '(?m)^OLLAMA_NUM_CTX=16384\r?$') $true
    Assert-True 'no 8192 left' ($after -match '(?m)^OLLAMA_NUM_CTX=8192') $false
    Assert-True 'other settings untouched' ($after -match '(?m)^OTHER_SETTING=keep-me\r?$') $true
    $backups = @(Get-ChildItem -Path $tmpDir -Filter 'decline.env.bak-*')
    Assert-True 'original backed up' ($backups.Count -eq 1) $true
    Assert-Equal 'backup holds the original content' (Get-Content -Path $backups[0].FullName -Raw) $original

    Write-Host '== Repair-LegacyNumCtx (nothing to do) =='
    $script:LastWarn = $null
    $script:LastOk = $null
    Repair-LegacyNumCtx -Path $newEnv
    Assert-True 'already-16384 file is left alone' ((Get-Content -Path $newEnv -Raw) -match 'OLLAMA_NUM_CTX=16384') $true
    Assert-True 'no warning for a current file' ([bool]$script:LastWarn) $false
    Assert-True 'no backup for a current file' ([bool](Get-ChildItem -Path $tmpDir -Filter 'new.env.bak-*')) $false
} finally {
    Remove-Item -Path $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($script:Failures -eq 0) {
    Write-Host "ALL $($script:Checks) ENV MIGRATION CHECKS PASSED" -ForegroundColor Green
    exit 0
}
Write-Host "$($script:Failures) of $($script:Checks) ENV MIGRATION CHECKS FAILED" -ForegroundColor Red
exit 1
