// Infrastructure for py-code-mode (without Container Apps)
// Deploy this first, push images, then deploy app.bicep

@description('Location for all resources')
param location string = resourceGroup().location

@description('Base name for all resources')
param baseName string = 'pycodemode'

// Unique suffix for globally unique names
var uniqueSuffix = uniqueString(resourceGroup().id)
var acrName = '${baseName}${uniqueSuffix}'
var envName = '${baseName}-env'
var storageName = '${baseName}${uniqueSuffix}'
var logWorkspaceName = '${baseName}-logs'
var openAiName = '${baseName}-openai'

// Redis Cache module
module redis 'redis.bicep' = {
  name: 'redis-deployment'
  params: {
    location: location
    baseName: baseName
  }
}

// Log Analytics Workspace (required for Container Apps)
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Azure Container Registry
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// Storage Account for artifacts
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

// File Share for artifacts
resource artifactsShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  name: '${storage.name}/default/artifacts'
  properties: {
    shareQuota: 5
  }
}

// File Share for configs
resource configsShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  name: '${storage.name}/default/configs'
  properties: {
    shareQuota: 1
  }
}

// Azure OpenAI Service
resource openAi 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = {
  name: openAiName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
  }
}

// GPT-4o deployment
resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = {
  parent: openAi
  name: 'gpt-4o'
  sku: {
    name: 'Standard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-08-06'
    }
  }
}

// Container Apps Environment
resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

// Storage mounts in environment
resource artifactsStorage 'Microsoft.App/managedEnvironments/storages@2023-05-01' = {
  parent: containerAppEnv
  name: 'artifacts-storage'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: 'artifacts'
      accessMode: 'ReadWrite'
    }
  }
}

resource configsStorage 'Microsoft.App/managedEnvironments/storages@2023-05-01' = {
  parent: containerAppEnv
  name: 'configs-storage'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: 'configs'
      accessMode: 'ReadOnly'
    }
  }
}

// Outputs
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
#disable-next-line outputs-should-not-contain-secrets
output acrPassword string = acr.listCredentials().passwords[0].value
output environmentName string = containerAppEnv.name
output environmentId string = containerAppEnv.id
output storageAccountName string = storage.name
output openAiEndpoint string = openAi.properties.endpoint
output openAiDeployment string = gpt4oDeployment.name

// Redis outputs
output redisHostname string = redis.outputs.hostname
#disable-next-line outputs-should-not-contain-secrets
output redisPrimaryKey string = redis.outputs.primaryKey
#disable-next-line outputs-should-not-contain-secrets
output redisConnectionString string = redis.outputs.connectionString
output redisName string = redis.outputs.name
