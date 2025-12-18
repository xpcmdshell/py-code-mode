// Azure Container Apps deployment for py-code-mode session server
// Deploys: Container Registry, Container Apps Environment, Session Server, Storage

@description('Location for all resources')
param location string = resourceGroup().location

@description('Base name for all resources')
param baseName string = 'pycodemode'

@description('Container image to deploy (pushed to ACR after infra creation)')
param imageName string = 'py-code-mode-tools'

@description('Container image tag')
param imageTag string = 'latest'

// Unique suffix for globally unique names
var uniqueSuffix = uniqueString(resourceGroup().id)
var acrName = '${baseName}${uniqueSuffix}'
var envName = '${baseName}-env'
var appName = 'session-server'
var storageName = '${baseName}${uniqueSuffix}'
var logWorkspaceName = '${baseName}-logs'

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
    shareQuota: 5 // 5 GB
  }
}

// File Share for configs
resource configsShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  name: '${storage.name}/default/configs'
  properties: {
    shareQuota: 1 // 1 GB
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

// Storage mount in environment
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

// Session Server Container App
resource sessionApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true  // Set to false for internal-only access
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'session'
          image: '${acr.properties.loginServer}/${imageName}:${imageTag}'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'PORT'
              value: '8080'
            }
            {
              name: 'TOOLS_CONFIG'
              value: '/workspace/configs/tools.yaml'
            }
            {
              name: 'SKILLS_DIR'
              value: '/workspace/configs/skills'
            }
            {
              name: 'ARTIFACTS_PATH'
              value: '/workspace/artifacts'
            }
          ]
          volumeMounts: [
            {
              volumeName: 'artifacts-vol'
              mountPath: '/workspace/artifacts'
            }
            {
              volumeName: 'configs-vol'
              mountPath: '/workspace/configs'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
      volumes: [
        {
          name: 'artifacts-vol'
          storageName: 'artifacts-storage'
          storageType: 'AzureFile'
        }
        {
          name: 'configs-vol'
          storageName: 'configs-storage'
          storageType: 'AzureFile'
        }
      ]
    }
  }
  dependsOn: [
    artifactsStorage
    configsStorage
  ]
}

// Outputs
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output sessionUrl string = 'https://${sessionApp.properties.configuration.ingress.fqdn}'
output storageAccountName string = storage.name
output resourceGroup string = resourceGroup().name
