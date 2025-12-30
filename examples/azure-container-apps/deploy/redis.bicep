// Azure Cache for Redis module
// Basic tier (C0 - 250MB) for tools/skills/artifacts storage

@description('Location for the Redis cache')
param location string

@description('Base name for the Redis cache')
param baseName string

// Unique suffix for globally unique names
var uniqueSuffix = uniqueString(resourceGroup().id)
var redisName = '${baseName}-redis-${uniqueSuffix}'

// Azure Cache for Redis - Basic tier
resource redisCache 'Microsoft.Cache/redis@2023-08-01' = {
  name: redisName
  location: location
  properties: {
    sku: {
      name: 'Basic'
      family: 'C'
      capacity: 0  // C0 - 250MB
    }
    enableNonSslPort: false  // TLS required
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'maxmemory-policy': 'volatile-lru'
    }
    publicNetworkAccess: 'Enabled'
  }
}

// Outputs
output hostname string = redisCache.properties.hostName
output sslPort int = redisCache.properties.sslPort
#disable-next-line outputs-should-not-contain-secrets
output primaryKey string = redisCache.listKeys().primaryKey
#disable-next-line outputs-should-not-contain-secrets
output connectionString string = 'rediss://:${redisCache.listKeys().primaryKey}@${redisCache.properties.hostName}:${redisCache.properties.sslPort}/0'
output name string = redisCache.name
