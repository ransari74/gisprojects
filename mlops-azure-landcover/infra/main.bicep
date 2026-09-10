@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Base name used to derive resource names')
param baseName string = 'mlopslandcover'

@description('AAD tenant ID for Key Vault RBAC')
param tenantId string = subscription().tenantId

var storageAccountName = toLower('${baseName}st${uniqueString(resourceGroup().id)}')
var keyVaultName = toLower('${baseName}kv${uniqueString(resourceGroup().id)}')
var acrName = toLower('${baseName}acr${uniqueString(resourceGroup().id)}')
var workspaceName = '${baseName}-ws'
var appInsightsName = '${baseName}-appi'

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storageDeploy'
  params: {
    location: location
    storageAccountName: storageAccountName
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyVaultDeploy'
  params: {
    location: location
    keyVaultName: keyVaultName
    tenantId: tenantId
  }
}

module acr 'modules/containerregistry.bicep' = {
  name: 'acrDeploy'
  params: {
    location: location
    acrName: acrName
  }
}

module workspace 'modules/workspace.bicep' = {
  name: 'workspaceDeploy'
  params: {
    location: location
    workspaceName: workspaceName
    storageAccountId: storage.outputs.storageAccountId
    keyVaultId: keyVault.outputs.keyVaultId
    acrId: acr.outputs.acrId
    applicationInsightsId: appInsights.id
  }
}

module compute 'modules/compute.bicep' = {
  name: 'computeDeploy'
  params: {
    location: location
    workspaceName: workspace.outputs.workspaceName
  }
}

output workspaceName string = workspace.outputs.workspaceName
output storageAccountName string = storage.outputs.storageAccountName
