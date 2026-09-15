#Requires -Version 7.0
<#
.SYNOPSIS
    SQLCheck 2.0 - Smoke test against a running deployment.

.DESCRIPTION
    Standalone script that can be run directly, and is also called
    automatically by deploy.ps1 after `docker compose up`. Performs two
    checks against a running SQLCheck instance:

      1. GET  {BaseUrl}/api/health   -> HTTP 200, body.status == "ok"
      2. POST {BaseUrl}/api/analyze  -> HTTP 200, body.compliance.status == "PASS"
         (a small, known-good, deterministic-rule-only example with
         include_ai:false, so this does not depend on Ollama/AI being
         reachable - the rule engine alone must always work per PRD)

    Prints a PASS/FAIL line per check and exits 0 only if both pass.

.PARAMETER BaseUrl
    Base URL of the running SQLCheck instance. Defaults to https://localhost
    (production is always reached on 443 -> internal 8000, see
    docker-compose.yml). Certificate validation is skipped since production
    uses a self-signed certificate (see backend/app/certgen.py).

.EXAMPLE
    .\smoke-test.ps1
.EXAMPLE
    .\smoke-test.ps1 -BaseUrl https://10.97.15.58
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://localhost'
)

$ErrorActionPreference = 'Stop'
$script:AllPassed = $true

function Write-CheckResult {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail = ''
    )
    if ($Passed) {
        Write-Host ("[PASS] {0}" -f $Name) -ForegroundColor Green
    } else {
        Write-Host ("[FAIL] {0}" -f $Name) -ForegroundColor Red
        $script:AllPassed = $false
    }
    if ($Detail) {
        Write-Host ("       {0}" -f $Detail) -ForegroundColor Gray
    }
}

function Get-HttpErrorDetail {
    param($ErrorRecord)
    $statusCodeText = ''
    if ($ErrorRecord.Exception.Response -and $ErrorRecord.Exception.Response.StatusCode) {
        $statusCodeText = " (HTTP $([int]$ErrorRecord.Exception.Response.StatusCode))"
    }
    return "連線失敗$statusCodeText - $($ErrorRecord.Exception.Message)"
}

Write-Host ''
Write-Host "SQLCheck 2.0 Smoke Test - $BaseUrl" -ForegroundColor Cyan
Write-Host '----------------------------------------------------'

# --- Check 1: GET /api/health ------------------------------------------
$healthUrl = "$BaseUrl/api/health"
try {
    $healthResponse = Invoke-WebRequest -Uri $healthUrl -SkipCertificateCheck -TimeoutSec 10 -ErrorAction Stop
    $healthBody = $healthResponse.Content | ConvertFrom-Json
    $healthOk = ($healthResponse.StatusCode -eq 200) -and ($healthBody.status -eq 'ok')
    $detail = "HTTP $($healthResponse.StatusCode), status=$($healthBody.status)"
} catch {
    $healthOk = $false
    $detail = Get-HttpErrorDetail -ErrorRecord $_
}
Write-CheckResult -Name "GET $healthUrl" -Passed $healthOk -Detail $detail

# --- Check 2: POST /api/analyze (rules-only, include_ai:false) ---------
$analyzeUrl = "$BaseUrl/api/analyze"
$payload = @{
    application_no = 'SMOKE-TEST'
    cost            = 1000
    sql             = 'SELECT * FROM T A WHERE A.X=1'
    include_ai      = $false
} | ConvertTo-Json

try {
    $analyzeResponse = Invoke-WebRequest -Uri $analyzeUrl -Method Post -Body $payload -ContentType 'application/json' -SkipCertificateCheck -TimeoutSec 30 -ErrorAction Stop
    $analyzeBody = $analyzeResponse.Content | ConvertFrom-Json
    $complianceStatus = $analyzeBody.compliance.status
    $analyzeOk = ($analyzeResponse.StatusCode -eq 200) -and ($complianceStatus -eq 'PASS')
    $detail = "HTTP $($analyzeResponse.StatusCode), compliance.status=$complianceStatus"
} catch {
    $analyzeOk = $false
    $detail = Get-HttpErrorDetail -ErrorRecord $_
}
Write-CheckResult -Name "POST $analyzeUrl (include_ai:false)" -Passed $analyzeOk -Detail $detail

Write-Host '----------------------------------------------------'
if ($script:AllPassed) {
    Write-Host 'Smoke test: 全數通過 (ALL PASSED)' -ForegroundColor Green
    exit 0
} else {
    Write-Host 'Smoke test: 有項目未通過 (SOME CHECKS FAILED)' -ForegroundColor Red
    exit 1
}
