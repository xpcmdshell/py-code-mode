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

@secure()
@description('Redis connection URL (rediss:// format)')
param redisUrl string

@secure()
@description('Session server authentication token')
param sessionAuthToken string

@secure()
@description('Anthropic API key for Claude models')
param anthropicApiKey string

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
        {
          name: 'redis-url'
          value: redisUrl
        }
        {
          name: 'session-auth-token'
          value: sessionAuthToken
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
              name: 'REDIS_URL'
              secretRef: 'redis-url'
            }
            {
              name: 'CONTAINER_AUTH_TOKEN'
              secretRef: 'session-auth-token'
            }
            {
              name: 'ALLOW_RUNTIME_DEPS'
              value: 'false'
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
            {
              name: 'REDIS_TOOLS_PREFIX'
              value: 'pycodemode:tools'
            }
            {
              name: 'REDIS_SKILLS_PREFIX'
              value: 'pycodemode:skills'
            }
            {
              name: 'REDIS_ARTIFACTS_PREFIX'
              value: 'pycodemode:artifacts'
            }
            {
              name: 'REDIS_DEPS_PREFIX'
              value: 'pycodemode:deps'
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
        {
          name: 'session-auth-token'
          value: sessionAuthToken
        }
        {
          name: 'anthropic-api-key'
          value: anthropicApiKey
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
              name: 'SESSION_AUTH_TOKEN'
              secretRef: 'session-auth-token'
            }
            {
              name: 'ANTHROPIC_API_KEY'
              secretRef: 'anthropic-api-key'
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

// Outputs
output agentUrl string = 'https://${agentApp.properties.configuration.ingress.fqdn}'
output sessionUrl string = 'http://${sessionApp.properties.configuration.ingress.fqdn}'
output agentAppName string = agentApp.name
output sessionAppName string = sessionApp.name
