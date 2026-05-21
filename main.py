# Copyright (c) Microsoft. All rights reserved.
"""Product catalog agent — LangGraph + Azure AI Foundry (responses protocol).

This agent answers questions about a product catalog by combining two
retrieval tools:

  1. **Azure AI Search** — hybrid search over indexed product documents
     (PDFs, Excel sheets, Word files, etc.) uploaded to an Azure AI Search
     index.

  2. **Bing Custom Search** — web search scoped to the company's public
     product website(s), configured via a Bing Custom Search instance.

The agent is built with LangGraph and integrates with Azure AI Foundry via
the ``azure-ai-agentserver-responses`` *responses protocol*, which provides:

  - Automatic multi-turn history management (via ``previous_response_id``)
  - Streaming text output back to the Foundry platform
  - Auto-tracing to Application Insights via ``langchain-azure-ai``

Architecture::

    User message
         │
         ▼
    ┌────────────────────────────────┐
    │   ResponsesAgentServerHost     │  ← Foundry hosting layer
    │   (azure-ai-agentserver)       │
    └────────────┬───────────────────┘
                 │ Fetch history + current input
                 ▼
    ┌────────────────────────────────┐
    │         LangGraph Graph        │
    │                                │
    │   START → chatbot ─────────────┼──▶ END (no tool calls)
    │              │                 │
    │              ▼ (tool calls)    │
    │           ToolNode             │
    │         ┌──────────────┐       │
    │         │ AI Search    │       │
    │         │ Bing Custom  │       │
    │         └──────────────┘       │
    │              │                 │
    │              └── back to chatbot
    └────────────────────────────────┘

Required environment variables:
    FOUNDRY_PROJECT_ENDPOINT        Foundry project endpoint (auto-injected)
    AZURE_AI_MODEL_DEPLOYMENT_NAME  Model deployment name (e.g., gpt-4o)
    AZURE_SEARCH_ENDPOINT           Azure AI Search service URL
    AZURE_SEARCH_INDEX_NAME         Name of the langchain-foundry index
    AZURE_SEARCH_API_KEY            API key (or omit for Managed Identity)
    BING_CUSTOM_SEARCH_SUBSCRIPTION_KEY  Bing Custom Search API key
    BING_CUSTOM_SEARCH_CONFIG_ID    Bing Custom Search configuration instance ID

Optional:
    APPLICATIONINSIGHTS_CONNECTION_STRING  Auto-injected in hosted containers
    AZURE_SEARCH_CONTENT_FIELD             Content field name (default: content)
    AZURE_SEARCH_SELECT_FIELDS             Fields to return (comma-separated)
    AZURE_SEARCH_TOP                       Max search hits (default: 5)
    BING_CUSTOM_SEARCH_COUNT               Max web results (default: 5)

Usage (local development)::

    cp .env.example .env  # fill in the values
    pip install -r requirements.txt
    python main.py

    # Test a single turn
    curl -N -X POST http://localhost:8088/responses \\
        -H "Content-Type: application/json" \\
        -d '{"model": "chat", "input": "Quais produtos vocês têm na linha premium?", "stream": true}'

    # Multi-turn: pass previous_response_id from the first response
    curl -N -X POST http://localhost:8088/responses \\
        -H "Content-Type: application/json" \\
        -d '{"model": "chat", "input": "E qual deles tem o menor preço?", "previous_response_id": "<ID>", "stream": true}'
"""

from __future__ import annotations

import asyncio
import logging
import os

# Load .env for local development (no-op when variables are already set)
from dotenv import load_dotenv
load_dotenv()
from typing import Annotated

from azure.identity import DefaultAzureCredential
from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)
from azure.ai.agentserver.responses.models import (
    MessageContentInputTextContent,
    MessageContentOutputTextContent,
)

from tools import TOOLS

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    logger.warning(
        "APPLICATIONINSIGHTS_CONNECTION_STRING not set — traces will not be "
        "exported to Application Insights. "
        "(This variable is auto-injected in hosted Foundry containers.)"
    )

# ── Required environment variables ────────────────────────────────────────────

FOUNDRY_PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
if not FOUNDRY_PROJECT_ENDPOINT:
    raise EnvironmentError(
        "FOUNDRY_PROJECT_ENDPOINT is not set. "
        "Set it to your Foundry project endpoint, or use 'azd ai agent run'."
    )

AZURE_AI_MODEL_DEPLOYMENT_NAME = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
if not AZURE_AI_MODEL_DEPLOYMENT_NAME:
    raise EnvironmentError(
        "AZURE_AI_MODEL_DEPLOYMENT_NAME is not set. "
        "Set it to your model deployment name as declared in agent.manifest.yaml."
    )

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "Você é um assistente especialista em catálogo de produtos. "
    "Ajude os usuários a encontrar informações sobre produtos, como preços, "
    "especificações técnicas, disponibilidade, comparações e recomendações. "
    "\n\n"
    "Você tem acesso a duas fontes de informação:\n"
    "1. **Catálogo interno (Azure AI Search)**: documentos indexados com dados "
    "detalhados dos produtos (fichas técnicas, tabelas de preços, manuais).\n"
    "2. **Site da empresa (Bing Custom Search)**: conteúdo público do site de "
    "produtos, incluindo páginas de produto, blog e FAQ.\n"
    "\n"
    "Sempre consulte as fontes disponíveis antes de responder. Se a informação "
    "vier de uma fonte específica, mencione de onde ela foi obtida. "
    "Seja preciso, objetivo e útil. Responda sempre em português."
)

# ── LangGraph state ───────────────────────────────────────────────────────────


class State(TypedDict):
    messages: Annotated[list, add_messages]


# ── Graph builder ─────────────────────────────────────────────────────────────


def _build_graph() -> StateGraph:
    """Compile the LangGraph agent graph with both retrieval tools.

    Graph topology:
        START → chatbot → (tool calls?) → tools → chatbot → … → END
    """
    llm = AzureAIOpenAIApiChatModel(
        project_endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        model=AZURE_AI_MODEL_DEPLOYMENT_NAME,
        streaming=True,
    )

    llm_with_tools = llm.bind_tools(TOOLS)

    def chatbot(state: State) -> dict:
        """Call the LLM with the current conversation messages."""
        # Prepend system message only on the first turn (no prior AI messages).
        messages = state["messages"]
        if not any(isinstance(m, AIMessage) for m in messages):
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        return {"messages": [llm_with_tools.invoke(messages)]}

    def route_tools(state: State) -> str:
        """Route to the tool node if the model produced tool calls, else end."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(State)
    graph.add_node("chatbot", chatbot)
    graph.add_node("tools", ToolNode(tools=TOOLS))
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", route_tools, {"tools": "tools", END: END})
    graph.add_edge("tools", "chatbot")
    return graph.compile()


GRAPH = _build_graph()

# ── History helpers ───────────────────────────────────────────────────────────


def _protocol_history_to_lc_messages(history: list) -> list:
    """Convert Foundry responses-protocol history items to LangChain messages.

    The history contains alternating input (human) and output (AI) items,
    each with a ``content`` list of typed content blocks.
    """
    messages = []
    for item in history:
        if not hasattr(item, "content") or not item.content:
            continue
        for block in item.content:
            if isinstance(block, MessageContentOutputTextContent) and block.text:
                messages.append(AIMessage(content=block.text))
            elif isinstance(block, MessageContentInputTextContent) and block.text:
                messages.append(HumanMessage(content=block.text))
    return messages


# ── Foundry responses-protocol wiring ─────────────────────────────────────────

app = ResponsesAgentServerHost(
    options=ResponsesServerOptions(default_fetch_history_count=20)
)


@app.response_handler
async def handle_create(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    """Run the LangGraph agent and stream the response back to the platform.

    This handler is invoked by the Foundry hosting layer for each new user
    message.  It:
      1. Fetches the conversation history from the platform (multi-turn).
      2. Converts the history to LangChain messages.
      3. Invokes the compiled LangGraph graph asynchronously.
      4. Streams the final AI message back as a ``TextResponse``.
    """

    async def run_graph():
        try:
            # Retrieve prior conversation turns managed by the platform.
            try:
                history = await context.get_history()
            except Exception:
                logger.debug("Could not fetch history — starting fresh.")
                history = []

            current_input = await context.get_input_text() or ""
            if not current_input.strip():
                yield "Por favor, faça uma pergunta sobre nossos produtos."
                return

            lc_messages = _protocol_history_to_lc_messages(history)
            lc_messages.append(HumanMessage(content=current_input))

            result = await GRAPH.ainvoke({"messages": lc_messages})

            raw = result["messages"][-1].content
            # The content can be a plain string or a list of content blocks
            # (when use_responses_api is active in the model client).
            if isinstance(raw, list):
                yield "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw
                )
            else:
                yield raw or ""

        except Exception as exc:
            logger.exception("Graph execution failed")
            yield f"[ERRO] {type(exc).__name__}: {exc}"

    return TextResponse(context, request, text=run_graph())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(
        "Starting product catalog agent on http://localhost:8088 "
        "(model: %s)",
        AZURE_AI_MODEL_DEPLOYMENT_NAME,
    )
    app.run()
