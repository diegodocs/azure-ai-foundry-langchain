targetScope = 'resourceGroup'

// ── Parameters ────────────────────────────────────────────────────────────────

@description('Localização para todos os recursos. Use "eastus" para maior disponibilidade de modelos.')
param location string = 'eastus'

@description('Nome base do projeto — prefixo usado em todos os recursos (máx. 12 chars).')
@maxLength(12)
param projectName string = 'langfoundry'

@description('Nome do deployment do modelo LLM no AI Services.')
param modelDeploymentName string = 'gpt-4.1'

@description('Versão do modelo LLM a ser deployado.')
param modelVersion string = '2025-04-14'

@description('Capacidade do deployment em milhares de tokens por minuto.')
@minValue(1)
@maxValue(300)
param modelCapacity int = 10

// ── Variables ─────────────────────────────────────────────────────────────────

var suffix             = take(uniqueString(resourceGroup().id), 6)
var aiServicesName     = '${projectName}-ai-${suffix}'
var searchServiceName  = '${projectName}-search-${suffix}'
var searchIndexName    = 'langchain-foundry'
var hubName            = '${projectName}-hub-${suffix}'
var projName           = '${projectName}-proj-${suffix}'
var storageName        = '${projectName}st${suffix}'
var keyVaultName       = '${projectName}-kv-${suffix}'
var logAnalyticsName   = '${projectName}-logs-${suffix}'
var appInsightsName    = '${projectName}-appins-${suffix}'

// ── Storage Account ───────────────────────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

// ── Key Vault ─────────────────────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// ── Log Analytics Workspace ───────────────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Application Insights ──────────────────────────────────────────────────────

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ── Azure AI Services (host do GPT-4.1) ──────────────────────────────────────

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiServicesName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: aiServicesName
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: modelDeploymentName
  sku: {
    name: 'Standard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelDeploymentName
      version: modelVersion
    }
  }
}

// ── Azure AI Search ───────────────────────────────────────────────────────────

resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'enabled'
  }
}

// ── AI Foundry Hub ────────────────────────────────────────────────────────────

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: hubName
  location: location
  kind: 'Hub'
  sku: { name: 'Basic', tier: 'Basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    storageAccount: storageAccount.id
    keyVault: keyVault.id
    applicationInsights: appInsights.id
  }
}

// Conexão Hub → AI Services (expõe o endpoint GPT-4.1 ao projeto)
resource hubAiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-10-01' = {
  parent: aiHub
  name: 'ai-services-connection'
  properties: {
    category: 'AIServices'
    target: aiServices.properties.endpoint
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: aiServices.id
    }
  }
}

// ── AI Foundry Project ────────────────────────────────────────────────────────

resource aiProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: projName
  location: location
  kind: 'Project'
  sku: { name: 'Basic', tier: 'Basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    hubResourceId: aiHub.id
  }
}

// ── Role Assignments ──────────────────────────────────────────────────────────

// Managed Identity do Projeto pode ler o índice AI Search
resource searchIndexReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, aiProject.id, '1407120a-92aa-4202-b7e9-c0e197c71c8f')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f') // Search Index Data Reader
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Managed Identity do Hub pode ler/escrever Blobs (ex: artefatos do workspace)
resource storageBlobContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, aiHub.id, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
    principalId: aiHub.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Outputs — mapeados para variáveis de ambiente pelo azd ───────────────────

// Endpoint do projeto Foundry (usado por AzureAIOpenAIApiChatModel)
output FOUNDRY_PROJECT_ENDPOINT string = 'https://${aiServicesName}.services.ai.azure.com/api/projects/${projName}'

// Nome do deployment do modelo (ex: gpt-4.1)
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = modelDeploymentName

// Azure AI Search
output AZURE_SEARCH_ENDPOINT string = 'https://${searchServiceName}.search.windows.net'
output AZURE_SEARCH_INDEX_NAME string = searchIndexName

// Admin key do AI Search — usada em desenvolvimento local.
// Em produção, use Managed Identity (deixe AZURE_SEARCH_API_KEY vazio).
output AZURE_SEARCH_API_KEY string = searchService.listAdminKeys().primaryKey

// Application Insights — injetado automaticamente em containers Foundry.
output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.properties.ConnectionString
