param location string
param workspaceName string
param storageAccountId string
param keyVaultId string
param acrId string
param applicationInsightsId string

resource workspace 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = {
  name: workspaceName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: workspaceName
    storageAccount: storageAccountId
    keyVault: keyVaultId
    containerRegistry: acrId
    applicationInsights: applicationInsightsId
    publicNetworkAccess: 'Enabled'
  }
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
}

output workspaceName string = workspace.name
output workspacePrincipalId string = workspace.identity.principalId
