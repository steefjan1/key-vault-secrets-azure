# Forces App Service to re-resolve all Key Vault references for the API
# without a restart. This is the documented escape hatch for the 24 hour cache.
# 'Continue' on purpose: under Windows PowerShell 5.1 with 'Stop', any stderr line from az
# (even a warning) becomes a terminating error. Exit codes are checked instead.
$ErrorActionPreference = 'Continue'

$apiName = (& azd env get-value API_NAME).Trim()
if ($LASTEXITCODE -ne 0) { throw 'azd env get-value API_NAME failed' }
$rg = (& azd env get-value AZURE_RESOURCE_GROUP).Trim()
if ($LASTEXITCODE -ne 0) { throw 'azd env get-value AZURE_RESOURCE_GROUP failed' }
$sub = (& az account show --query id -o tsv).Trim()
if ($LASTEXITCODE -ne 0) { throw 'az account show failed' }

$url = "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.Web/sites/$apiName/config/configreferences/appsettings/refresh?api-version=2022-03-01"
# Pre-quoted on purpose: az is az.cmd on Windows and cmd.exe splits an unquoted URL at '&'
& az rest --method post --url ('"' + $url + '"')
if ($LASTEXITCODE -ne 0) { throw 'az rest refresh failed' }
Write-Host "Key Vault references of $apiName refreshed."
