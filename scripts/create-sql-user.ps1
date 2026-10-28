# Creates the contained database user for the API's managed identity and
# grants it the minimum it needs. Runs as the SQL Entra admin (the person who
# ran azd) using an access token from az, so no SQL password exists anywhere.
#
# The user is created WITH SID from the identity's client id instead of
# FROM EXTERNAL PROVIDER, so the script does not need Microsoft Graph
# permissions on the SQL server. Windows PowerShell 5.1 compatible.
# 'Continue' on purpose: under Windows PowerShell 5.1 with 'Stop', any stderr line from az
# (even a warning) becomes a terminating error. Exit codes are checked instead.
$ErrorActionPreference = 'Continue'

function Get-AzdValue {
    param([string]$Name)
    $v = & azd env get-value $Name
    if ($LASTEXITCODE -ne 0) { throw "azd env get-value $Name failed" }
    return $v.Trim()
}

$server = Get-AzdValue 'SQL_SERVER_FQDN'
$database = Get-AzdValue 'SQL_DATABASE_NAME'
$clientId = Get-AzdValue 'API_IDENTITY_CLIENT_ID'
$identityName = Get-AzdValue 'API_IDENTITY_NAME'

$token = (& az account get-access-token --resource https://database.windows.net --query accessToken -o tsv)
if ($LASTEXITCODE -ne 0) { throw 'az account get-access-token failed' }
$token = $token.Trim()

# Client id (GUID) -> SID bytes as SQL expects them for an Entra service principal
$guid = [Guid]$clientId
$sidHex = '0x' + (($guid.ToByteArray() | ForEach-Object { $_.ToString('X2') }) -join '')

$sql = @"
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$identityName')
BEGIN
    EXEC('CREATE USER [$identityName] WITH SID = $sidHex, TYPE = E');
END;
ALTER ROLE db_datareader ADD MEMBER [$identityName];
ALTER ROLE db_datawriter ADD MEMBER [$identityName];
ALTER ROLE db_ddladmin ADD MEMBER [$identityName];
"@

Add-Type -AssemblyName System.Data
$conn = New-Object System.Data.SqlClient.SqlConnection
$conn.ConnectionString = "Server=tcp:$server,1433;Database=$database;Encrypt=True;TrustServerCertificate=False;Connection Timeout=60;"
$conn.AccessToken = $token

$attempt = 0
$opened = $false
while (-not $opened -and $attempt -lt 6) {
    $attempt++
    try {
        $conn.Open()
        $opened = $true
    } catch {
        # A serverless database that is still paused, or a firewall rule that
        # is still propagating, both clear up within a minute.
        Write-Host "Open attempt $attempt failed: $($_.Exception.Message). Retrying in 15 s."
        Start-Sleep -Seconds 15
    }
}
if (-not $opened) { throw "Could not open a connection to $server/$database" }

$cmd = $conn.CreateCommand()
$cmd.CommandText = $sql
$cmd.CommandTimeout = 120
[void]$cmd.ExecuteNonQuery()
$conn.Close()

Write-Host "SQL user [$identityName] exists with SID $sidHex and is db_datareader, db_datawriter, db_ddladmin on $database."
