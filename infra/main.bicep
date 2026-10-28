targetScope = 'resourceGroup'

@minLength(1)
@description('azd environment name, used as the name prefix')
param environmentName string

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Object id of the person running azd (gets Key Vault Secrets Officer and becomes the SQL Entra admin)')
param deployerObjectId string

@description('UPN or display name of the person running azd (SQL Entra admin login)')
param deployerLogin string

@description('Public IP of the machine running azd, so the post-provision script can reach SQL')
param deployerIp string = ''

@description('How often the configuration provider reloads secrets, in minutes')
param providerReloadMinutes int = 5

@description('Initial value of the ExternalApiKey secret; rotated later by measure/rotate.py')
@secure()
param initialApiKey string = newGuid()

var prefix = toLower(take(replace(environmentName, '_', '-'), 12))
var suffix = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var tags = { 'azd-env-name': environmentName, project: 'key-vault-secrets-azure' }

var keyVaultName = 'kv-${prefix}-${take(suffix, 6)}'
var sqlServerName = 'sql-${prefix}-${suffix}'
var sqlDbName = 'orders'
var apiName = 'app-${prefix}-api-${take(suffix, 6)}'

// Built-in role definition ids
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

// ---------------------------------------------------------------- identity
resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-api'
  location: location
  tags: tags
}

// ------------------------------------------------------------- monitoring
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${prefix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// -------------------------------------------------------------- key vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    // enablePurgeProtection is deliberately not set, so `azd down --purge`
    // can clean up a demo. Turn it on for anything that holds real secrets.
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// The one secret the sample actually needs: a key for a third-party API.
resource externalApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'ExternalApiKey'
  properties: {
    value: initialApiKey
    contentType: 'text/plain'
  }
}

// Every SecretGet lands in Log Analytics, with the identity that asked.
resource keyVaultAudit 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'audit-to-log-analytics'
  scope: keyVault
  properties: {
    workspaceId: logAnalytics.id
    logs: [
      { category: 'AuditEvent', enabled: true }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

// --------------------------------------------------------------------- sql
resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  tags: tags
  properties: {
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      login: deployerLogin
      sid: deployerObjectId
      tenantId: subscription().tenantId
      principalType: 'User'
    }
  }

  resource allowAzure 'firewallRules' = {
    name: 'AllowAzureServices'
    properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  }

  resource allowDeployer 'firewallRules' = if (!empty(deployerIp)) {
    name: 'AllowDeployer'
    properties: { startIpAddress: deployerIp, endIpAddress: deployerIp }
  }
}

resource sqlDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDbName
  location: location
  tags: tags
  sku: { name: 'GP_S_Gen5', tier: 'GeneralPurpose', family: 'Gen5', capacity: 1 }
  properties: {
    minCapacity: json('0.5')
    autoPauseDelay: 60
    zoneRedundant: false
  }
}

// -------------------------------------------------------------- app service
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-${prefix}'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: 'B1', tier: 'Basic' }
  properties: { reserved: true }
}

resource api 'Microsoft.Web/sites@2023-12-01' = {
  name: apiName
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  kind: 'app,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    // Key Vault references are resolved by the platform with THIS identity,
    // not with the identity your code uses.
    keyVaultReferenceIdentity: apiIdentity.id
    siteConfig: {
      linuxFxVersion: 'DOTNETCORE|8.0'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        // Tells DefaultAzureCredential / ManagedIdentityCredential which identity to use
        { name: 'AZURE_CLIENT_ID', value: apiIdentity.properties.clientId }
        { name: 'KeyVault__Uri', value: keyVault.properties.vaultUri }
        { name: 'Provider__ReloadMinutes', value: string(providerReloadMinutes) }
        // Path 1: App Service resolves this reference, the code sees a plain string
        { name: 'ExternalApi__KeyFromReference', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=ExternalApiKey)' }
        // No password anywhere: SqlClient gets a token for the managed identity
        { name: 'Sql__ConnectionString', value: 'Server=tcp:${sqlServer.properties.fullyQualifiedDomainName},1433;Database=${sqlDbName};Authentication=Active Directory Default;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'false' }
      ]
    }
  }
}

// --------------------------------------------------------- role assignments
// Role assignments that use a managed identity's principalId live in their
// own module, otherwise Bicep cannot compute the assignment name at plan time.
module roles 'modules/roles.bicep' = {
  name: 'roles'
  params: {
    keyVaultName: keyVault.name
    apiPrincipalId: apiIdentity.properties.principalId
    deployerObjectId: deployerObjectId
    secretsUserRoleId: keyVaultSecretsUserRoleId
    secretsOfficerRoleId: keyVaultSecretsOfficerRoleId
  }
}

// ------------------------------------------------------------------ outputs
output API_NAME string = api.name
output API_URL string = 'https://${api.properties.defaultHostName}'
output API_IDENTITY_CLIENT_ID string = apiIdentity.properties.clientId
output API_IDENTITY_NAME string = apiIdentity.name
output KEY_VAULT_NAME string = keyVault.name
output KEY_VAULT_URI string = keyVault.properties.vaultUri
output SQL_SERVER_FQDN string = sqlServer.properties.fullyQualifiedDomainName
output SQL_DATABASE_NAME string = sqlDbName
output LOG_ANALYTICS_WORKSPACE_ID string = logAnalytics.properties.customerId
output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.properties.ConnectionString
