# Product Catalog Agent — LangGraph + Azure AI Foundry

Agente de catálogo de produtos construído com **LangGraph** (ecossistema LangChain) e hospedado no **Azure AI Foundry** usando o protocolo *bring-your-own / responses*.

O agente combina duas fontes de dados para responder perguntas sobre produtos:

| Fonte | Tecnologia | O que contém |
|---|---|---|
| **Catálogo interno** | Azure AI Search | Fichas técnicas, tabelas de preços, manuais (PDFs, XLSX, DOCX) |
| **Site da empresa** | Bing Custom Search | Páginas públicas de produtos, blog, FAQ |

## Arquitetura

```
Usuário
  │
  ▼
ResponsesAgentServerHost (Foundry)
  │
  ▼
LangGraph StateGraph
  ├─ Node: chatbot  (AzureAIOpenAIApiChatModel / GPT-4o)
  │       │
  │       ├─ Tool: search_products_in_azure_ai_search
  │       │          └─ azure-search-documents SDK (busca híbrida)
  │       │
  │       └─ Tool: search_products_on_website
  │                  └─ Bing Custom Search REST API
  └─ Node: tools (ToolNode)
```

## Pré-requisitos

- Python 3.12+
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az`)
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) (`azd`)
- Acesso a uma assinatura Azure

## Fase 0 — Provisionamento Azure com `azd`

Todo o provisionamento de infraestrutura é feito via `azd` usando o template Bicep em `infra/main.bicep`.

### Recursos criados automaticamente

| Recurso | Tipo | Finalidade |
|---|---|---|
| `langfoundry-ai-<suffix>` | Azure AI Services | Deployment GPT-4.1 |
| `langfoundry-hub-<suffix>` | AI Foundry Hub | Orchestração e conexão com AI Services |
| `langfoundry-proj-<suffix>` | AI Foundry Project | Endpoint do agente (`FOUNDRY_PROJECT_ENDPOINT`) |
| `langfoundry-search-<suffix>` | Azure AI Search (Basic) | Índice de produtos |
| `langfoundry-appins-<suffix>` | Application Insights | Traces do agente |

### 1. Login

```bash
az login
azd auth login
```

### 2. Provisionar

```bash
# Apenas na primeira vez — inicializa o ambiente azd (aceite os padrões)
azd init

# Provisionamento completo: cria todos os recursos + índice AI Search
azd provision
```

O hook `postprovision` cria o índice `langchain-foundry` no AI Search automaticamente.

> **Personalizar parâmetros**: edite `infra/main.bicepparam` para mudar região,
> nome do projeto ou capacidade do modelo antes de rodar `azd provision`.

### 3. Exportar variáveis de ambiente

```bash
# Exporta os outputs do Bicep para o arquivo .env
azd env get-values > .env
```

O `.env` gerado conterá `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_SEARCH_ENDPOINT`,
`AZURE_SEARCH_API_KEY` e demais variáveis preenchidas automaticamente.

### 4. Grounding with Bing Custom Search (configuração manual)

O recurso Bing Custom Search requer configuração de domínios via portal e
**não pode ser totalmente automatizado**. Execute os passos abaixo:

1. No [Azure portal](https://portal.azure.com), busque **"Grounding with Bing Custom Search"** e crie o recurso no mesmo Resource Group.
2. No recurso criado → **Resource Management** → **Configurations** → **+ Create**.
3. Adicione os domínios do site de produtos (ex: `https://www.meusite.com.br/produtos`).
4. Anote o **Configuration ID** → defina em `BING_CUSTOM_SEARCH_CONFIG_ID`.
5. Em **Keys**, copie a chave → defina em `BING_CUSTOM_SEARCH_SUBSCRIPTION_KEY`.

Adicione essas duas variáveis ao `.env` gerado pelo `azd env get-values`, ou registre-as no ambiente azd:

```bash
azd env set BING_CUSTOM_SEARCH_SUBSCRIPTION_KEY <chave>
azd env set BING_CUSTOM_SEARCH_CONFIG_ID <config-id>
azd env get-values > .env   # re-exporta com os novos valores
```

## Fase 1 — Configuração Local

```bash
# Clone o repositório (se ainda não fez)
git clone <repo-url>
cd azure-ai-foundry-langchain

# Crie e ative o ambiente virtual
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Instale as dependências
pip install -r requirements.txt

# Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com os valores dos recursos criados na Fase 0
```

### Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | Ex: `https://<account>.services.ai.azure.com/api/projects/<project>` |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Nome do deployment GPT-4o no Foundry |
| `AZURE_SEARCH_ENDPOINT` | Ex: `https://langchain-foundry-search.search.windows.net` |
| `AZURE_SEARCH_INDEX_NAME` | Nome do índice (ex: `langchain-foundry`) |
| `AZURE_SEARCH_API_KEY` | API key do AI Search (ou deixe vazio para usar Managed Identity) |
| `WEB_SEARCH_SITE` | Domínio para restringir buscas (ex: `seusite.com.br`). Deixe vazio para busca irrestrita. |
| `WEB_SEARCH_COUNT` | Número máximo de resultados web (padrão: 5) |
| `WEB_SEARCH_REGION` | Região DuckDuckGo (padrão: `br-pt` para Português-Brasil) |

## Fase 2 — Executar Localmente

Existem dois modos de execução local:

### Modo A — Interface Web (Vue.js + FastAPI)

```bash
# Terminal 1: backend FastAPI (porta 8088)
python api.py

# Terminal 2: frontend Vue.js (porta 5173)
cd frontend
npm install
npm run dev
```

Acesse `http://localhost:5173` no navegador.

### Modo B — Azure AI Foundry Responses Protocol (sem frontend)

```bash
# Inicie o agente server
python main.py

# Em outro terminal — teste uma pergunta:
curl -N -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"model": "chat", "input": "Quais produtos vocês têm na linha premium?", "stream": true}'

# Conversa multi-turn (use o ID retornado na resposta anterior):
curl -N -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"model": "chat", "input": "E qual tem o menor preço?", "previous_response_id": "<ID>", "stream": true}'
```

## Fase 3 — Deploy no Azure AI Foundry

```bash
# Build do container, push para ACR e deploy no Foundry
azd deploy
```

> **Pré-requisito**: `azd provision` já deve ter sido executado com sucesso.

Após o deploy, o agente estará disponível no [Foundry portal](https://ai.azure.com) em **Agents → langchain-foundry-agent**.

Para provisionar e fazer deploy em uma única etapa:

```bash
azd up   # equivalente a azd provision + azd deploy
```

## Estrutura do Projeto

```
azure-ai-foundry-langchain/
├── main.py                         # Agente LangGraph + wiring Foundry
├── tools/
│   ├── __init__.py                 # Exporta lista TOOLS
│   ├── ai_search_tool.py           # Tool: Azure AI Search (busca híbrida)
│   └── bing_custom_search_tool.py  # Tool: Bing Custom Search (site)
├── infra/
│   ├── main.bicep                  # Template Bicep — todos os recursos Azure
│   └── main.bicepparam             # Parâmetros padrão do Bicep
├── scripts/
│   └── create-search-index.ps1     # Hook postprovision: cria índice AI Search
├── azure.yaml                      # Configuração do projeto azd
├── requirements.txt
├── .env.example                    # Template de variáveis de ambiente
├── agent.yaml                      # Configuração do agente Foundry
├── agent.manifest.yaml             # Manifest do agente (modelos, versão)
├── Dockerfile                      # Container para deploy no Foundry
└── .dockerignore
```

## Customizações Comuns

### Adicionar mais campos ao índice de busca

Edite `AZURE_SEARCH_SELECT_FIELDS` no `.env`:
```
AZURE_SEARCH_SELECT_FIELDS=id,title,content,category,price,brand
```

### Mudar o idioma dos resultados do Bing

Em `tools/bing_custom_search_tool.py`, altere o parâmetro `mkt`:
```python
params = {
    ...
    "mkt": "pt-BR",  # ou "en-US", "es-MX", etc.
}
```

### Aumentar o número de resultados

```
AZURE_SEARCH_TOP=10
BING_CUSTOM_SEARCH_COUNT=10
```

## Referências

- [Azure AI Foundry — Hosted Agents (bring-your-own)](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents)
- [LangGraph — Quickstart](https://langchain-ai.github.io/langgraph/tutorials/introduction/)
- [Azure AI Search — Hybrid Search](https://learn.microsoft.com/azure/search/hybrid-search-overview)
- [Grounding with Bing Custom Search](https://learn.microsoft.com/azure/ai-services/agents/how-to/tools/bing-custom-search)