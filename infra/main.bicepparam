using './main.bicep'

// Localização dos recursos. Use 'eastus' para maior disponibilidade de GPT-4.1.
param location = 'eastus'

// Prefixo dos recursos (máx. 12 chars). Será combinado com um sufixo único.
param projectName = 'langfoundry'

// Modelo a ser deployado. Verifique disponibilidade em:
// https://learn.microsoft.com/azure/ai-services/openai/concepts/models
param modelDeploymentName = 'gpt-4.1'
param modelVersion = '2025-04-14'

// Capacidade em milhares de TPM (tokens por minuto). Ajuste conforme sua cota.
param modelCapacity = 10
