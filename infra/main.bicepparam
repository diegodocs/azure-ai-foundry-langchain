using './main.bicep'

// Localização principal — eastus2, onde os recursos existentes estão provisionados.
param location = 'eastus2'

// Nomes dos recursos existentes em rg-langchain-lab-001.
param aiFoundryAccountName = 'aif-langchain-lab-001'
param aiFoundryProjectName = 'proj-langchain-lab-001'
param keyVaultName         = 'kv-langchain-lab-001'
param appInsightsName      = 'app-ins-langchain-lab-001'
param bingAccountName      = 'bing-langchain-lab-001'
param searchServiceName    = 'search-langchain-lab-001'

// AI Search está em centralus (diferente da localização principal).
param searchServiceLocation = 'centralus'

// Modelo a ser deployado. Verifique disponibilidade em:
// https://learn.microsoft.com/azure/ai-services/openai/concepts/models
param modelDeploymentName = 'gpt-4.1'
param modelVersion        = '2025-04-14'

// Capacidade em milhares de TPM (tokens por minuto). Ajuste conforme sua cota.
param modelCapacity = 10

// Nome do índice Azure AI Search.
param searchIndexName = 'langchain-foundry'
