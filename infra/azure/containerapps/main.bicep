targetScope = 'resourceGroup'

@description('Prefix used for resource names.')
@minLength(3)
param prefix string

@description('Azure region.')
param location string = resourceGroup().location

@description('Container image used by both API and worker.')
param containerImage string

@description('Existing Azure Container Registry name used for image pulls.')
@minLength(5)
param containerRegistryName string

@description('Application environment value.')
param appEnv string = 'prod'

@allowed([
  'database'
  'storage_queue'
  'service_bus'
])
@description('Provisioning queue backend mode.')
param queueBackend string = 'storage_queue'

@description('Enable Service Bus resources and role assignments.')
param serviceBusEnabled bool = false

@description('Allow secret/key fallback in runtime config. Keep false for production.')
param allowApiKeyFallback bool = false

@description('Entra JWKS URL.')
param jwtJwksUrl string

@description('Expected JWT issuer.')
param jwtIssuer string

@description('Expected JWT audience.')
param jwtAudience string

@description('Optional Azure AI Foundry endpoint.')
param foundryEndpoint string = ''

@description('PostgreSQL admin username.')
@minLength(3)
param postgresAdminUser string

@secure()
@description('PostgreSQL admin password.')
param postgresAdminPassword string

@description('PostgreSQL flexible server SKU.')
param postgresSkuName string = 'Standard_B1ms'

@description('PostgreSQL server version.')
param postgresVersion string = '16'

@description('PostgreSQL storage in MB.')
param postgresStorageMb int = 32768

@description('PostgreSQL application database name.')
param postgresDatabaseName string = 'saas_platform'

@description('Default RPM applied per tenant+agent key.')
param defaultRateLimitRpm int = 60

@description('Enable Azure Cache for Redis deployment.')
param redisEnabled bool = true

@description('Provisioning worker poll interval in seconds.')
param provisioningWorkerPollSeconds int = 2

@description('Provisioning queue name.')
param provisioningQueueName string = 'provisioning-jobs'

@description('Provisioning dead-letter queue name.')
param provisioningDeadLetterQueueName string = 'provisioning-jobs-deadletter'

@description('Redis SKU family.')
param redisSkuFamily string = 'C'

@description('Redis SKU name.')
param redisSkuName string = 'Basic'

@description('Redis capacity.')
param redisCapacity int = 1

@description('API min replicas.')
param apiMinReplicas int = 1

@description('API max replicas.')
param apiMaxReplicas int = 5

@description('Worker min replicas.')
param workerMinReplicas int = 1

@description('Worker max replicas.')
param workerMaxReplicas int = 10

@description('Storage Queue Data Contributor role definition id.')
param storageQueueDataContributorRoleDefinitionId string = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
)

@description('AcrPull role definition id.')
param acrPullRoleDefinitionId string = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

@description('Key Vault user role definition id.')
param keyVaultUserRoleDefinitionId string = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)

@description('Optional Service Bus role definition id for API/worker identities.')
param serviceBusRoleDefinitionId string = ''

var suffix = uniqueString(resourceGroup().id, prefix)
var apiAppName = '${prefix}-api'
var workerAppName = '${prefix}-worker'
var apiIdentityName = '${prefix}-api-mi'
var workerIdentityName = '${prefix}-worker-mi'
var lawName = '${prefix}-law'
var appInsightsName = '${prefix}-appi'
var managedEnvName = '${prefix}-cae'
var keyVaultName = take(toLower(replace('${prefix}-kv-${suffix}', '-', '')), 24)
var storageName = take(toLower(replace('${prefix}st${suffix}', '-', '')), 24)
var redisName = take(toLower(replace('${prefix}-redis-${suffix}', '-', '')), 63)
var serviceBusName = take(toLower(replace('${prefix}-sb-${suffix}', '-', '')), 50)
var postgresName = take(toLower(replace('${prefix}-pg-${suffix}', '-', '')), 63)
var postgresStorageGb = max(32, int(postgresStorageMb / 1024))
var tenantCatalogDsn = 'postgresql+psycopg://${postgresAdminUser}:${postgresAdminPassword}@${postgresName}.postgres.database.azure.com:5432/${postgresDatabaseName}?sslmode=require'
var redisUrl = redisEnabled ? 'redis://:${listKeys(redis!.id, redis!.apiVersion).primaryKey}@${redis!.properties.hostName}:6380/0?ssl=true' : 'redis://disabled'
var storageQueueAccountUrl = 'https://${storage.name}.queue.${environment().suffixes.storage}'
var serviceBusNamespace = serviceBusEnabled ? '${serviceBus.name}.servicebus.windows.net' : ''
var keyVaultUrl = 'https://${keyVault.name}${environment().suffixes.keyvaultDns}'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource managedEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: managedEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: apiIdentityName
  location: location
}

resource workerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: workerIdentityName
  location: location
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    publicNetworkAccess: 'Enabled'
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource storageQueueService 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource storageQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = {
  parent: storageQueueService
  name: provisioningQueueName
}

resource storageDeadLetterQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = {
  parent: storageQueueService
  name: provisioningDeadLetterQueueName
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = if (serviceBusEnabled) {
  name: serviceBusName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

resource serviceBusQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = if (serviceBusEnabled) {
  parent: serviceBus
  name: provisioningQueueName
  properties: {
    lockDuration: 'PT30S'
    maxDeliveryCount: 10
    deadLetteringOnMessageExpiration: true
  }
}

resource serviceBusDeadLetterQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = if (serviceBusEnabled) {
  parent: serviceBus
  name: provisioningDeadLetterQueueName
  properties: {
    lockDuration: 'PT30S'
    maxDeliveryCount: 10
    deadLetteringOnMessageExpiration: true
  }
}

resource redis 'Microsoft.Cache/Redis@2023-08-01' = if (redisEnabled) {
  name: redisName
  location: location
  properties: {
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
  sku: {
    family: redisSkuFamily
    name: redisSkuName
    capacity: redisCapacity
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: postgresName
  location: location
  sku: {
    name: postgresSkuName
    tier: contains(postgresSkuName, 'B') ? 'Burstable' : 'GeneralPurpose'
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: postgresStorageGb
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: postgres
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apiIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      registries: [
        {
          server: acr.properties.loginServer
          identity: apiIdentity.id
        }
      ]
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8080
        transport: 'auto'
      }
      secrets: [
        {
          name: 'tenant-catalog-dsn'
          value: tenantCatalogDsn
        }
        {
          name: 'redis-url'
          value: redisUrl
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
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
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 30
              periodSeconds: 20
            }
          ]
          env: [
            { name: 'APP_ENV', value: appEnv }
            { name: 'TENANT_CATALOG_DSN', secretRef: 'tenant-catalog-dsn' }
            { name: 'PROVISIONING_QUEUE_BACKEND', value: queueBackend }
            { name: 'AZURE_STORAGE_QUEUE_ACCOUNT_URL', value: storageQueueAccountUrl }
            { name: 'AZURE_STORAGE_QUEUE_NAME', value: storageQueue.name }
            { name: 'AZURE_STORAGE_QUEUE_DEAD_LETTER_QUEUE_NAME', value: storageDeadLetterQueue.name }
            { name: 'AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE', value: serviceBusNamespace }
            { name: 'AZURE_SERVICE_BUS_QUEUE_NAME', value: provisioningQueueName }
            { name: 'AZURE_SERVICE_BUS_DEAD_LETTER_QUEUE_NAME', value: provisioningDeadLetterQueueName }
            { name: 'AZURE_AI_PROJECT_ENDPOINT', value: foundryEndpoint }
            { name: 'AZURE_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'AZURE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentity.properties.clientId }
            { name: 'ALLOW_API_KEY_FALLBACK', value: allowApiKeyFallback ? 'true' : 'false' }
            { name: 'KEY_VAULT_URL', value: keyVaultUrl }
            { name: 'RATE_LIMIT_BACKEND', value: redisEnabled ? 'redis' : 'memory' }
            { name: 'RATE_LIMIT_REDIS_URL', secretRef: 'redis-url' }
            { name: 'RATE_LIMIT_REDIS_FAIL_OPEN', value: redisEnabled ? 'false' : 'true' }
            { name: 'DEFAULT_RATE_LIMIT_RPM', value: string(defaultRateLimitRpm) }
            { name: 'JWT_JWKS_URL', value: jwtJwksUrl }
            { name: 'JWT_ISSUER', value: jwtIssuer }
            { name: 'JWT_AUDIENCE', value: jwtAudience }
            { name: 'JWT_ALGORITHM', value: 'RS256' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'OTEL_SERVICE_NAME', value: 'saas-platform-api' }
          ]
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
      }
    }
  }
}

resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workerIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      registries: [
        {
          server: acr.properties.loginServer
          identity: workerIdentity.id
        }
      ]
      secrets: [
        {
          name: 'tenant-catalog-dsn'
          value: tenantCatalogDsn
        }
        {
          name: 'redis-url'
          value: redisUrl
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: containerImage
          command: [
            'saas-platform-worker'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'APP_ENV', value: appEnv }
            { name: 'TENANT_CATALOG_DSN', secretRef: 'tenant-catalog-dsn' }
            { name: 'PROVISIONING_QUEUE_BACKEND', value: queueBackend }
            { name: 'AZURE_STORAGE_QUEUE_ACCOUNT_URL', value: storageQueueAccountUrl }
            { name: 'AZURE_STORAGE_QUEUE_NAME', value: storageQueue.name }
            { name: 'AZURE_STORAGE_QUEUE_DEAD_LETTER_QUEUE_NAME', value: storageDeadLetterQueue.name }
            { name: 'AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE', value: serviceBusNamespace }
            { name: 'AZURE_SERVICE_BUS_QUEUE_NAME', value: provisioningQueueName }
            { name: 'AZURE_SERVICE_BUS_DEAD_LETTER_QUEUE_NAME', value: provisioningDeadLetterQueueName }
            { name: 'AZURE_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'AZURE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentity.properties.clientId }
            { name: 'ALLOW_API_KEY_FALLBACK', value: allowApiKeyFallback ? 'true' : 'false' }
            { name: 'KEY_VAULT_URL', value: keyVaultUrl }
            { name: 'PROVISIONING_WORKER_POLL_SECONDS', value: string(provisioningWorkerPollSeconds) }
            { name: 'RATE_LIMIT_BACKEND', value: redisEnabled ? 'redis' : 'memory' }
            { name: 'RATE_LIMIT_REDIS_URL', secretRef: 'redis-url' }
            { name: 'RATE_LIMIT_REDIS_FAIL_OPEN', value: redisEnabled ? 'false' : 'true' }
            { name: 'DEFAULT_RATE_LIMIT_RPM', value: string(defaultRateLimitRpm) }
            { name: 'JWT_JWKS_URL', value: jwtJwksUrl }
            { name: 'JWT_ISSUER', value: jwtIssuer }
            { name: 'JWT_AUDIENCE', value: jwtAudience }
            { name: 'JWT_ALGORITHM', value: 'RS256' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'OTEL_SERVICE_NAME', value: 'saas-platform-worker' }
          ]
        }
      ]
      scale: {
        minReplicas: workerMinReplicas
        maxReplicas: workerMaxReplicas
      }
    }
  }
}

resource apiStorageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, apiIdentity.id, 'storage-queue-contributor')
  properties: {
    principalId: apiIdentity.properties.principalId
    roleDefinitionId: storageQueueDataContributorRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource apiAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, apiIdentity.id, 'acr-pull')
  properties: {
    principalId: apiIdentity.properties.principalId
    roleDefinitionId: acrPullRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource workerStorageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, workerIdentity.id, 'storage-queue-contributor')
  properties: {
    principalId: workerIdentity.properties.principalId
    roleDefinitionId: storageQueueDataContributorRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource workerAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, workerIdentity.id, 'acr-pull')
  properties: {
    principalId: workerIdentity.properties.principalId
    roleDefinitionId: acrPullRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource apiKeyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, apiIdentity.id, 'kv-secrets-user')
  properties: {
    principalId: apiIdentity.properties.principalId
    roleDefinitionId: keyVaultUserRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource workerKeyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, workerIdentity.id, 'kv-secrets-user')
  properties: {
    principalId: workerIdentity.properties.principalId
    roleDefinitionId: keyVaultUserRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource apiServiceBusRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (serviceBusEnabled && !empty(serviceBusRoleDefinitionId)) {
  scope: serviceBus
  name: guid(serviceBus.id, apiIdentity.id, 'service-bus-role')
  properties: {
    principalId: apiIdentity.properties.principalId
    roleDefinitionId: serviceBusRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

resource workerServiceBusRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (serviceBusEnabled && !empty(serviceBusRoleDefinitionId)) {
  scope: serviceBus
  name: guid(serviceBus.id, workerIdentity.id, 'service-bus-role')
  properties: {
    principalId: workerIdentity.properties.principalId
    roleDefinitionId: serviceBusRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}

output apiAppUrl string = 'https://${apiApp.properties.configuration.ingress.fqdn}'
output apiAppName string = apiApp.name
output workerAppName string = workerApp.name
output apiIdentityPrincipalId string = apiIdentity.properties.principalId
output workerIdentityPrincipalId string = workerIdentity.properties.principalId
output keyVaultName string = keyVault.name
output keyVaultUrl string = keyVaultUrl
output postgresServerName string = postgres.name
output postgresDatabaseName string = postgresDb.name
output redisHostName string = redisEnabled ? redis!.properties.hostName : ''
output storageAccountName string = storage.name
output serviceBusNamespace string = serviceBusEnabled ? serviceBus.name : ''
