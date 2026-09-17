#Requires -Version 7.0
<#
.SYNOPSIS
    Behavioural tests for the Ollama (TCP 11434) firewall helpers in deploy.ps1.

.DESCRIPTION
    deploy.ps1's Step 3 must guarantee that "only the SQLCheck container may
    reach this host's Ollama API" (PRD §46). The host-side commands themselves
    can only be exercised on the real Windows 11 + Docker Desktop host, but the
    decision logic (port matching, source-scope classification, same-name rule
    validation, fail-closed behaviour) is pure PowerShell and is tested here.

    The tests parse deploy.ps1 with the PowerShell AST and dot-source only the
    helper functions under test - deploy.ps1 itself is never executed, so
    nothing is deployed, no firewall rule is touched and no environment
    variable is changed. The firewall cmdlets are replaced by in-memory mocks.

.EXAMPLE
    # From the repository root (PowerShell 7 on any OS):
    pwsh -NoProfile -File deploy/tests/firewall-helpers.Tests.ps1
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

# ---------------------------------------------------------------------------
# Load the helper functions under test (no execution of deploy.ps1 itself)
# ---------------------------------------------------------------------------
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

$wanted = @(
    'Test-PortListContains', 'Test-WslInterfaceAlias', 'Test-AddressWithinRange',
    'Test-BroadRemoteAddressEntry', 'Test-BroadRemoteAddressList', 'Test-OllamaRuleScoped',
    'Test-BroadLanAllow', 'Get-OllamaFirewallAudit', 'Get-OllamaRuleRemediationText',
    'Get-OllamaRuleMismatch', 'Stop-OllamaFirewallStep', 'Assert-OllamaFirewallRule'
)
$source = [System.Text.StringBuilder]::new()
foreach ($f in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $f.Name) { [void]$source.AppendLine($f.Extent.Text) }
}
. ([scriptblock]::Create($source.ToString()))

# deploy.ps1 defines these in its own scope; provide silent/recording stubs here.
$script:WarnLog = @()
Set-Item -Path function:Write-Ok -Value { param([string]$Message) $script:LastOk = $Message }
Set-Item -Path function:Write-Warn -Value {
    param([string]$Message)
    $script:WarnLog = @($script:WarnLog) + $Message
    $script:LastWarn = $Message
}
Set-Item -Path function:Write-Info -Value { param([string]$Message) $script:LastInfo = $Message }
Set-Item -Path function:Write-Fail -Value { param([string]$Message) $script:LastFail = $Message }

class OllamaFirewallCheckException : System.Exception {
    OllamaFirewallCheckException([string]$message) : base($message) {}
}

function Assert-True {
    param([string]$Name, [bool]$Actual, [bool]$Expected = $true)
    $script:Checks++
    if ($Actual -eq $Expected) {
        Write-Host "  PASS  $Name"
    } else {
        $script:Failures++
        Write-Host "  FAIL  $Name (expected $Expected, got $Actual)" -ForegroundColor Red
    }
}

function Assert-Equal {
    param([string]$Name, [object]$Actual, [object]$Expected)
    $script:Checks++
    $a = if ($null -eq $Actual) { '<null>' } else { [string]$Actual }
    $e = if ($null -eq $Expected) { '<null>' } else { [string]$Expected }
    if ($a -eq $e) {
        Write-Host "  PASS  $Name"
    } else {
        $script:Failures++
        Write-Host "  FAIL  $Name (expected '$e', got '$a')" -ForegroundColor Red
    }
}

Write-Host '== Test-PortListContains =='
Assert-True '11434'                        (Test-PortListContains '11434' 11434)
Assert-True '11434-11435'                  (Test-PortListContains '11434-11435' 11434)
Assert-True '11430-11440'                  (Test-PortListContains '11430-11440' 11434)
Assert-True '80,11434'                     (Test-PortListContains '80,11434' 11434)
Assert-True 'Any'                          (Test-PortListContains 'Any' 11434)
Assert-True 'spaces: 11434, 11435'         (Test-PortListContains '11434, 11435' 11434)
Assert-True 'range 11400-11433'            (Test-PortListContains '11400-11433' 11434) $false
Assert-True '443'                          (Test-PortListContains '443' 11434) $false
Assert-True '114340'                       (Test-PortListContains '114340' 11434) $false
Assert-True 'empty'                        (Test-PortListContains '' 11434) $false
Assert-True 'null'                         (Test-PortListContains $null 11434) $false

Write-Host '== Test-WslInterfaceAlias =='
Assert-True "'vEthernet (WSL)'"                    (Test-WslInterfaceAlias 'vEthernet (WSL)')
Assert-True "'vEthernet (WSL (Hyper-V firewall))'" (Test-WslInterfaceAlias 'vEthernet (WSL (Hyper-V firewall))')
Assert-True 'array with WSL entry'                 (Test-WslInterfaceAlias @('Ethernet', 'vEthernet (WSL)'))
Assert-True "'Ethernet'"                           (Test-WslInterfaceAlias 'Ethernet') $false
Assert-True "'vEthernet (Default Switch)'"         (Test-WslInterfaceAlias 'vEthernet (Default Switch)') $false
Assert-True 'null'                                 (Test-WslInterfaceAlias $null) $false

Write-Host '== Test-AddressWithinRange =='
Assert-True '172.18.0.0/16 within 172.16.0.0/12'   (Test-AddressWithinRange '172.18.0.0/16' '172.16.0.0/12')
Assert-True '172.16.0.0/12 equals range'           (Test-AddressWithinRange '172.16.0.0/12' '172.16.0.0/12')
Assert-True '172.16.0.0/8 is wider'                (Test-AddressWithinRange '172.16.0.0/8' '172.16.0.0/12') $false
Assert-True '10.0.0.0/8 is not docker'             (Test-AddressWithinRange '10.0.0.0/8' '172.16.0.0/12') $false
Assert-True '127.0.0.1/32 is not docker'           (Test-AddressWithinRange '127.0.0.1/32' '172.16.0.0/12') $false
Assert-True '192.168.0.0/16 is not docker'         (Test-AddressWithinRange '192.168.0.0/16' '172.16.0.0/12') $false
Assert-True '172.15.0.0/16 is below the range'     (Test-AddressWithinRange '172.15.0.0/16' '172.16.0.0/12') $false
Assert-True '172.31.255.0/24 is inside'            (Test-AddressWithinRange '172.31.255.0/24' '172.16.0.0/12')
Assert-True '172.32.0.0/16 is above the range'     (Test-AddressWithinRange '172.32.0.0/16' '172.16.0.0/12') $false

Write-Host '== Test-BroadRemoteAddressEntry =='
Assert-True 'Any'                                  (Test-BroadRemoteAddressEntry -Entry 'Any' -DockerRange '172.16.0.0/12')
Assert-True 'LocalSubnet'                          (Test-BroadRemoteAddressEntry -Entry 'LocalSubnet' -DockerRange '172.16.0.0/12')
Assert-True 'empty'                                (Test-BroadRemoteAddressEntry -Entry '' -DockerRange '172.16.0.0/12')
Assert-True '*'                                    (Test-BroadRemoteAddressEntry -Entry '*' -DockerRange '172.16.0.0/12')
Assert-True 'bare LAN host 10.97.15.58'            (Test-BroadRemoteAddressEntry -Entry '10.97.15.58' -DockerRange '172.16.0.0/12')
Assert-True '172.18.0.0/16 is docker'              (Test-BroadRemoteAddressEntry -Entry '172.18.0.0/16' -DockerRange '172.16.0.0/12') $false

Write-Host '== Test-BroadRemoteAddressList =='
Assert-True 'null list'                            (Test-BroadRemoteAddressList -Values $null -DockerRange '172.16.0.0/12')
Assert-True 'empty array'                          (Test-BroadRemoteAddressList -Values @() -DockerRange '172.16.0.0/12')
Assert-True 'Any array'                            (Test-BroadRemoteAddressList -Values @('Any') -DockerRange '172.16.0.0/12')
Assert-True 'mixed docker + LAN'                   (Test-BroadRemoteAddressList -Values @('172.18.0.0/16', '10.0.0.0/8') -DockerRange '172.16.0.0/12')
Assert-True 'docker ranges only'                   (Test-BroadRemoteAddressList -Values @('172.18.0.0/16', '172.19.0.0/16') -DockerRange '172.16.0.0/12') $false

Write-Host '== Test-OllamaRuleScoped =='
Assert-True 'WSL interface, no address'            (Test-OllamaRuleScoped -InterfaceAlias 'vEthernet (WSL)' -RemoteAddress $null -DockerRemoteAddress '172.16.0.0/12')
Assert-True 'docker range, no interface'           (Test-OllamaRuleScoped -InterfaceAlias $null -RemoteAddress '172.18.0.0/16' -DockerRemoteAddress '172.16.0.0/12')
Assert-True 'no interface + Any'                   (Test-OllamaRuleScoped -InterfaceAlias $null -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'Ethernet + Any'                       (Test-OllamaRuleScoped -InterfaceAlias 'Ethernet' -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'Ethernet + no address'                (Test-OllamaRuleScoped -InterfaceAlias 'Ethernet' -RemoteAddress @() -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'WSL + LAN range widens the scope'     (Test-OllamaRuleScoped -InterfaceAlias 'vEthernet (WSL)' -RemoteAddress '10.0.0.0/8' -DockerRemoteAddress '172.16.0.0/12') $false

Write-Host '== Test-BroadLanAllow =='
Assert-True 'installer-style Allow/Any/Any'        (Test-BroadLanAllow -Enabled $true -Inbound $true -Allow $true -InterfaceAlias $null -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12')
Assert-True 'LocalSubnet allow'                    (Test-BroadLanAllow -Enabled $true -Inbound $true -Allow $true -InterfaceAlias @() -RemoteAddress 'LocalSubnet' -DockerRemoteAddress '172.16.0.0/12')
Assert-True 'scoped to WSL'                        (Test-BroadLanAllow -Enabled $true -Inbound $true -Allow $true -InterfaceAlias 'vEthernet (WSL)' -RemoteAddress $null -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'scoped to docker range'               (Test-BroadLanAllow -Enabled $true -Inbound $true -Allow $true -InterfaceAlias $null -RemoteAddress '172.16.0.0/12' -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'disabled rule'                        (Test-BroadLanAllow -Enabled $false -Inbound $true -Allow $true -InterfaceAlias $null -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'Block rule'                           (Test-BroadLanAllow -Enabled $true -Inbound $true -Allow $false -InterfaceAlias $null -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12') $false
Assert-True 'outbound rule'                        (Test-BroadLanAllow -Enabled $true -Inbound $false -Allow $true -InterfaceAlias $null -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12') $false

Write-Host '== Get-OllamaFirewallAudit (mocked firewall) =='
# Fake firewall: the correctly-scoped SQLCheck rule, an installer-style
# LocalSubnet allow rule, and an unrelated 443 rule that must not show up.
$script:FakeOwnedAlias = 'vEthernet (WSL)'
$script:FakeOwnedRemote = $null
$script:FakeOwnedLocalPort = '11434'

function New-FakeRule {
    param($id, $name, $alias, $remote, $port = '11434', $action = 'Allow', $enabled = 'True', $direction = 'Inbound')
    [pscustomobject]@{ InstanceID = $id; DisplayName = $name; Enabled = $enabled; Direction = $direction; Action = $action; Profile = 'Any' }
}
function Get-NetFirewallRule {
    param([string]$DisplayName, [string]$Direction)
    if ($PSBoundParameters.ContainsKey('DisplayName')) {
        if ($DisplayName -eq 'SQLCheck - Ollama API (container only)') { return $script:FakeOwned }
        return $null
    }
    return @($script:FakeOwned, $script:FakeRogue, $script:Fake443)
}
# The real Get-NetFirewall*Filter cmdlets take no pipeline input when listing
# every filter, and return a single rule's filter when bound from the pipeline.
function Get-NetFirewallPortFilter {
    param([Parameter(ValueFromPipeline)]$InputObject)
    process {
        $all = @(
            [pscustomobject]@{ InstanceID = 'id-owned'; LocalPort = [string]$script:FakeOwnedLocalPort },
            [pscustomobject]@{ InstanceID = 'id-rogue'; LocalPort = '11434' },
            [pscustomobject]@{ InstanceID = 'id-443';   LocalPort = '443' }
        )
        if ($null -eq $InputObject) { return $all }
        return @($all | Where-Object { $_.InstanceID -eq $InputObject.InstanceID })
    }
}
function Get-NetFirewallInterfaceFilter {
    param([Parameter(ValueFromPipeline)]$InputObject)
    process {
        $all = @(
            [pscustomobject]@{ InstanceID = 'id-owned'; InterfaceAlias = $script:FakeOwnedAlias },
            [pscustomobject]@{ InstanceID = 'id-rogue'; InterfaceAlias = $null },
            [pscustomobject]@{ InstanceID = 'id-443';   InterfaceAlias = $null }
        )
        if ($null -eq $InputObject) { return $all }
        return @($all | Where-Object { $_.InstanceID -eq $InputObject.InstanceID })
    }
}
function Get-NetFirewallAddressFilter {
    param([Parameter(ValueFromPipeline)]$InputObject)
    process {
        $all = @(
            [pscustomobject]@{ InstanceID = 'id-owned'; RemoteAddress = $script:FakeOwnedRemote },
            [pscustomobject]@{ InstanceID = 'id-rogue'; RemoteAddress = 'LocalSubnet' },
            [pscustomobject]@{ InstanceID = 'id-443';   RemoteAddress = 'Any' }
        )
        if ($null -eq $InputObject) { return $all }
        return @($all | Where-Object { $_.InstanceID -eq $InputObject.InstanceID })
    }
}

$script:FakeOwned = New-FakeRule 'id-owned' 'SQLCheck - Ollama API (container only)' 'vEthernet (WSL)' $null
$script:FakeRogue = New-FakeRule 'id-rogue' 'Ollama API' $null 'LocalSubnet'
$script:Fake443 = New-FakeRule 'id-443' 'SQLCheck - HTTPS (LAN)' $null 'Any' '443'

$audit = @(Get-OllamaFirewallAudit -LocalPort 11434)
Assert-Equal 'audit returns only 11434 rules'      $audit.Count 2
Assert-Equal 'audit finds the rogue rule'          $audit[1].DisplayName 'Ollama API'
Assert-Equal 'rogue remote address preserved'      $audit[1].RemoteAddress 'LocalSubnet'
Assert-True  'rogue rule is flagged as broad LAN'  (Test-BroadLanAllow -Enabled $audit[1].Enabled -Inbound ($audit[1].Direction -eq 'Inbound') -Allow ($audit[1].Action -eq 'Allow') -InterfaceAlias $audit[1].InterfaceAlias -RemoteAddress $audit[1].RemoteAddress -DockerRemoteAddress '172.16.0.0/12')
Assert-True  'owned rule is not flagged'           (Test-BroadLanAllow -Enabled $audit[0].Enabled -Inbound ($audit[0].Direction -eq 'Inbound') -Allow ($audit[0].Action -eq 'Allow') -InterfaceAlias $audit[0].InterfaceAlias -RemoteAddress $audit[0].RemoteAddress -DockerRemoteAddress '172.16.0.0/12') $false

Write-Host '== Assert-OllamaFirewallRule =='
Assert-OllamaFirewallRule -DisplayName 'SQLCheck - Ollama API (container only)' -DockerRemoteAddress '172.16.0.0/12'
Assert-True 'correctly scoped rule verifies' ($script:LastOk -like '*驗證通過*')

$script:FakeOwned = New-FakeRule 'id-owned' 'SQLCheck - Ollama API (container only)' $null 'Any'
$script:FakeOwnedAlias = $null
$script:FakeOwnedRemote = 'Any'
$threw = $false
try { Assert-OllamaFirewallRule -DisplayName 'SQLCheck - Ollama API (container only)' -DockerRemoteAddress '172.16.0.0/12' }
catch { $threw = $true }
Assert-True 'wide-open same-name rule is rejected' $threw

Write-Host '== Get-OllamaRuleMismatch =='
$m = Get-OllamaRuleMismatch -Rule ([pscustomobject]@{ Enabled = 'True'; Direction = 'Inbound'; Action = 'Allow'; LocalPort = '11434' }) -InterfaceAlias 'vEthernet (WSL)' -RemoteAddress $null -DockerRemoteAddress '172.16.0.0/12'
Assert-Equal 'valid rule has no mismatch' $m.Count 0
$m2 = Get-OllamaRuleMismatch -Rule ([pscustomobject]@{ Enabled = 'True'; Direction = 'Inbound'; Action = 'Allow'; LocalPort = '443' }) -InterfaceAlias $null -RemoteAddress 'Any' -DockerRemoteAddress '172.16.0.0/12'
Assert-Equal 'wrong port + wide scope => 2 mismatches' $m2.Count 2

Write-Host '== Stop-OllamaFirewallStep (fail-closed) =='
$threw = $false
try {
    Stop-OllamaFirewallStep -Problem 'synthetic problem' -Remediation 'synthetic remediation' -BreakGlass:$false
} catch {
    $threw = $true
    $msg = $_.Exception.Message
}
Assert-True 'throws without -BreakGlassFirewall' $threw
Assert-True 'message names the rollback command' ($msg -like '*Remove-NetFirewallRule*')

$script:WarnLog = @()
$threw = $false
try {
    # -Remediation is echoed with Write-Host by design; keep the test output clean.
    Stop-OllamaFirewallStep -Problem 'synthetic problem' -Remediation 'synthetic remediation' -BreakGlass:$true 6>&1 | Out-Null
} catch { $threw = $true }
Assert-True 'break-glass continues (no throw)' $threw $false
Assert-True 'break-glass prints a loud warning' ([bool](@($script:WarnLog) -like '*BreakGlassFirewall*'))

Write-Host '== Get-OllamaRuleRemediationText =='
$text = Get-OllamaRuleRemediationText -Rule ([pscustomobject]@{ DisplayName = 'Ollama API'; Profile = 'Any'; RemoteAddress = 'LocalSubnet'; InterfaceAlias = $null; Action = 'Allow'; LocalPort = '11434' }) -DockerRemoteAddress '172.16.0.0/12'
Assert-True 'remediation names the offending rule' ($text -like '*Ollama API*')
Assert-True 'remediation offers narrowing command' ($text -like '*Set-NetFirewallRule*RemoteAddress*')
Assert-True 'remediation offers disable command' ($text -like '*Enabled False*')
Assert-True 'remediation warns about other apps' ($text -like '*其他*應用程式*')

Write-Host ''
if ($script:Failures -eq 0) {
    Write-Host "ALL $($script:Checks) FIREWALL HELPER CHECKS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$($script:Failures) / $($script:Checks) FIREWALL HELPER CHECKS FAILED" -ForegroundColor Red
    exit 1
}
