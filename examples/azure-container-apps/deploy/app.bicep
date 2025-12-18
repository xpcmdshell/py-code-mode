// Container App deployments (run after pushing images to ACR)

@description('Location for all resources')
param location string = resourceGroup().location

@description('Container Apps Environment ID')
param environmentId string

@description('ACR login server')
param acrLoginServer string

@description('ACR username')
param acrUsername string

@secure()
@description('ACR password')
param acrPassword string

@description('Azure OpenAI endpoint')
param openAiEndpoint string

@description('Azure OpenAI deployment name')
param openAiDeployment string = 'gpt-4o'

// Session Server - internal only, provides code execution
resource sessionApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'session-server'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      ingress: {
        external: false  // Internal only - agent connects to this
        targetPort: 8080
        transport: 'http'
      }
      registries: [
        {
          server: acrLoginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'session'
          image: '${acrLoginServer}/py-code-mode-session:latest'
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
              name: 'SKILLS_PATH'
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
}

// Agent Server - external, accepts tasks from users
resource agentApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'agent-server'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      ingress: {
        external: true  // Public endpoint for users
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'agent'
          image: '${acrLoginServer}/py-code-mode-agent:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'PORT'
              value: '8080'
            }
            {
              name: 'SESSION_URL'
              value: 'http://session-server'  // Internal DNS name
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: openAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: openAiDeployment
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
  dependsOn: [
    sessionApp
  ]
}

// Grant agent managed identity access to Azure OpenAI
// The agent uses DefaultAzureCredential which will use the managed identity
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: split(openAiEndpoint, '.')[0]
}

// Outputs
output agentUrl string = 'https://${agentApp.properties.configuration.ingress.fqdn}'
output sessionUrl string = 'http://${sessionApp.properties.configuration.ingress.fqdn}'
output agentAppName string = agentApp.name
output sessionAppName string = sessionApp.name
