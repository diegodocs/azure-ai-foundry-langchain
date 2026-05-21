#!/usr/bin/env pwsh
# scripts/create-search-index.ps1
#
# Hook postprovision do azd — cria o índice "langchain-foundry" no Azure AI Search.
# Executado automaticamente após `azd provision`.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-AzdEnvValue([string]$key) {
    $val = azd env get-value $key 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($val)) { return $null }
    return $val.Trim()
}

$searchEndpoint = Get-AzdEnvValue 'AZURE_SEARCH_ENDPOINT'
$searchKey      = Get-AzdEnvValue 'AZURE_SEARCH_API_KEY'

if (-not $searchEndpoint -or -not $searchKey) {
    Write-Warning "Não foi possível obter AZURE_SEARCH_ENDPOINT ou AZURE_SEARCH_API_KEY do azd env. Pulando criação do índice."
    exit 0
}

$indexName = 'langchain-foundry'
$apiVersion = '2023-11-01'

# Verifica se o índice já existe
try {
    $null = Invoke-RestMethod `
        -Uri "$searchEndpoint/indexes/$indexName`?api-version=$apiVersion" `
        -Method GET `
        -Headers @{ 'api-key' = $searchKey }
    Write-Host "✓ Índice '$indexName' já existe. Nenhuma ação necessária."
    exit 0
} catch {
    # 404 = não existe, prosseguir com a criação
    if ($_.Exception.Response.StatusCode.value__ -ne 404) {
        Write-Warning "Erro ao verificar índice existente: $($_.Exception.Message)"
    }
}

# Define o schema do índice
$indexBody = @{
    name   = $indexName
    fields = @(
        @{ name = 'id';            type = 'Edm.String';             key = $true;  filterable = $true;  retrievable = $true }
        @{ name = 'title';         type = 'Edm.String';             searchable = $true;  retrievable = $true }
        @{ name = 'content';       type = 'Edm.String';             searchable = $true;  retrievable = $true }
        @{ name = 'category';      type = 'Edm.String';             filterable = $true;  facetable = $true; retrievable = $true }
        @{ name = 'price';         type = 'Edm.Double';             filterable = $true;  sortable = $true;  retrievable = $true }
        @{ name = 'brand';         type = 'Edm.String';             filterable = $true;  retrievable = $true }
        @{
            name                = 'contentVector'
            type                = 'Collection(Edm.Single)'
            searchable          = $true
            retrievable         = $false
            dimensions          = 1536
            vectorSearchProfile = 'default-profile'
        }
    )
    vectorSearch = @{
        profiles   = @(@{ name = 'default-profile'; algorithm = 'default-hnsw' })
        algorithms = @(@{
            name           = 'default-hnsw'
            kind           = 'hnsw'
            hnswParameters = @{ metric = 'cosine' }
        })
    }
    semantic = @{
        configurations = @(@{
            name             = 'default'
            prioritizedFields = @{
                titleField               = @{ fieldName = 'title' }
                prioritizedContentFields = @(@{ fieldName = 'content' })
            }
        })
    }
} | ConvertTo-Json -Depth 10

try {
    $result = Invoke-RestMethod `
        -Uri "$searchEndpoint/indexes?api-version=$apiVersion" `
        -Method POST `
        -Headers @{ 'api-key' = $searchKey; 'Content-Type' = 'application/json' } `
        -Body $indexBody
    Write-Host "✓ Índice '$($result.name)' criado com $($result.fields.Count) campos."
} catch {
    $errBody = $_.ErrorDetails.Message | ConvertFrom-Json -ErrorAction SilentlyContinue
    Write-Warning "Falha ao criar índice: $($errBody.error.message ?? $_.Exception.Message)"
    exit 1
}
