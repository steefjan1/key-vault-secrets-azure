# Fills the azd environment with who is deploying, so Bicep can make that
# person the SQL Entra admin and a Key Vault Secrets Officer.
#
# Reads the object id and login from the claims of the ARM access token you
# already hold, so it needs no Microsoft Graph call (az ad signed-in-user show
# can hang or fail in multi-tenant MFA setups). Values that are already set in
# the environment are kept.
#
# Windows PowerShell 5.1 compatible: no ternaries, no ??, no && / ||.
# 'Continue' on purpose: under 5.1 with 'Stop', any stderr line from az
# (even a warning) becomes a terminating error. Exit codes are checked instead.
$ErrorActionPreference = 'Continue'

function Get-ExistingValue {
    param([string]$Name)
    $v = & azd env get-value $Name 2>$null
    if ($LASTEXITCODE -ne 0) { return '' }
    return ([string]$v).Trim()
}

function Set-EnvValue {
    param([string]$Name, [string]$Value)
    & azd env set $Name $Value
    if ($LASTEXITCODE -ne 0) { throw "azd env set $Name failed" }
}

$objectId = Get-ExistingValue 'DEPLOYER_OBJECT_ID'
$login = Get-ExistingValue 'DEPLOYER_LOGIN'

if ([string]::IsNullOrWhiteSpace($objectId) -or [string]::IsNullOrWhiteSpace($login)) {
    $token = (& az account get-access-token --query accessToken -o tsv)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) { throw 'az account get-access-token failed; run az login --tenant <tenant> first' }
    $payload = $token.Trim().Split('.')[1].Replace('-', '+').Replace('_', '/')
    $payload += '=' * ((4 - $payload.Length % 4) % 4)
    $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json

    if ([string]::IsNullOrWhiteSpace($objectId)) { $objectId = [string]$claims.oid }
    if ([string]::IsNullOrWhiteSpace($login)) {
        # upn for a member account; unique_name or email for a guest / Microsoft account
        foreach ($candidate in @($claims.upn, $claims.unique_name, $claims.email, $claims.name)) {
            if (-not [string]::IsNullOrWhiteSpace($candidate)) { $login = [string]$candidate; break }
        }
    }
    if ([string]::IsNullOrWhiteSpace($objectId)) { throw 'No oid claim in the access token' }
    if ([string]::IsNullOrWhiteSpace($login)) { throw 'No upn/unique_name/email claim in the access token; set DEPLOYER_LOGIN with azd env set' }
}

$ip = Get-ExistingValue 'DEPLOYER_IP'
if ([string]::IsNullOrWhiteSpace($ip)) {
    try {
        $ip = ([string](Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 10)).Trim()
    } catch {
        Write-Warning "Could not determine public IP, the SQL firewall rule for this machine is skipped: $($_.Exception.Message)"
        $ip = ''
    }
}

Set-EnvValue 'DEPLOYER_OBJECT_ID' $objectId
Set-EnvValue 'DEPLOYER_LOGIN' $login
Set-EnvValue 'DEPLOYER_IP' $ip

Write-Host "Deployer: $login ($objectId), IP: $ip"
