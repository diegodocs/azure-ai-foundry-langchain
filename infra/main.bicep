targetScope = 'resourceGroup'

// ── Parameters ────────────────────────────────────────────────────────────────

@description('Localização principal dos recursos (AI Foundry, Key Vault, App Insights).')
param location string = 'eastus2'

@description('Nome da conta Azure AI Foundry.')
param aiFoundryAccountName string = 'aif-langchain-lab-001'

@description('Nome do projeto dentro da conta AI Foundry.')
param aiFoundryProjectName string = 'proj-langchain-lab-001'

@description('Nome do Key Vault.')
param keyVaultName string = 'kv-langchain-lab-001'

@description('Nome do Application Insights.')
param appInsightsName string = 'app-ins-langchain-lab-001'

@description('Nome da conta Bing Custom Search.')
param bingAccountName string = 'bing-langchain-lab-001'

@description('Nome do serviço Azure AI Search.')
param searchServiceName string = 'search-langchain-lab-001'

@description('Localização do Azure AI Search (pode diferir da localização principal).')
param searchServiceLocation string = 'centralus'

@description('Nome do deployment do modelo LLM na conta AI Foundry.')
param modelDeploymentName string = 'gpt-4.1'

@description('Versão do modelo LLM a ser deployado.')
param modelVersion string = '2025-04-14'

@description('Capacidade do deployment em milhares de tokens por minuto.')
@minValue(1)
@maxValue(300)
param modelCapacity int = 10

@description('Nome do índice Azure AI Search.')
param searchIndexName string = 'langchain-foundry'

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

// ── Application Insights ──────────────────────────────────────────────────────

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

// ── Azure AI Foundry Account ──────────────────────────────────────────────────
// Novo modelo unificado: substitui o par Hub + Project de ML Services.

resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiFoundryAccountName
  location: location
  kind: 'AIFoundry'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: aiFoundryAccountName
  }
}

// ── Model Deployment ──────────────────────────────────────────────────────────

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiFoundryAccount
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

// ── AI Foundry Project ────────────────────────────────────────────────────────
// Novo modelo: projeto aninhado na conta AI Foundry (substitui ML workspace Project).

resource aiFoundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: aiFoundryAccount
  name: aiFoundryProjectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {}
}

// ── Azure AI Search ───────────────────────────────────────────────────────────

resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: searchServiceLocation
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'enabled'
  }
}

// ── Bing Custom Search ────────────────────────────────────────────────────────

resource bingSearch 'Microsoft.Bing/accounts@2020-06-10' = {
  name: bingAccountName
  location: 'global'
  kind: 'Bing.CustomSearch'
  sku: { name: 'S1' }
}

// ── Role Assignments ──────────────────────────────────────────────────────────

// Managed Identity do Projeto AI Foundry pode ler o índice AI Search
resource searchIndexReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, aiFoundryProject.id, '1407120a-92aa-4202-b7e9-c0e197c71c8f')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f') // Search Index Data Reader
    principalId: aiFoundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Outputs — mapeados para variáveis de ambiente pelo azd ───────────────────

// Endpoint do projeto Foundry (usado pela SDK azure-ai-projects)
output FOUNDRY_PROJECT_ENDPOINT string = 'https://${aiFoundryAccountName}.services.ai.azure.com/api/projects/${aiFoundryProjectName}'

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
