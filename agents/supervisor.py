"""Multi-agent LangGraph supervisor.

Three specialised agents are wired into a single compiled graph:

  ┌──────────┐
  │Supervisor│ — classifies intent → bing | search | ticket
  └──────────┘
       │
  ┌────┴──────────────────────────────┐
  │           │                       │
  ▼           ▼                       ▼
BingAgent  SearchAgent          TicketAgent
(web)      (AI Search catalog)  (MCP tickets)
"""
from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from azure.identity import DefaultAzureCredential
from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from tools.ai_search_tool import search_products_in_azure_ai_search
from tools.bing_custom_search_tool import search_products_on_website

logger = logging.getLogger(__name__)

_FOUNDRY_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
_MODEL_NAME = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]

# ── System prompts ────────────────────────────────────────────────────────────

_SUPERVISOR_PROMPT = """\
You are a routing agent. Read the user's message and decide which specialised \
agent should handle it.

Available agents:
- bing    : Questions about website content, company news, online articles, \
general product information found on the web.
- search  : Questions about the internal product catalog — prices, technical \
specs, stock, product comparisons using indexed documents.
- ticket  : Requests to open, register, list or close a support ticket / \
chamado.

Reply with ONLY one of these three words: bing  search  ticket"""

_BING_PROMPT = """\
Você é um especialista em pesquisa web. Utilize a ferramenta de Bing Custom \
Search para encontrar informações no site da empresa.
Cite sempre a URL da fonte. Responda em português, de forma objetiva e clara."""

_SEARCH_PROMPT = """\
Você é um especialista em catálogo de produtos. Utilize a ferramenta de \
Azure AI Search para consultar o catálogo interno.
Inclua preços, especificações e disponibilidade quando disponíveis. \
Responda em português."""

_TICKET_PROMPT = """\
Você é um especialista em suporte ao cliente. Sua função é gerenciar chamados \
de suporte.

Para criar um chamado colete:
• Título — resumo do problema (obrigatório)
• Descrição — detalhes do problema (obrigatório)
• Prioridade — baixa | média | alta | crítica (padrão: média)
• Categoria — suporte | faturamento | técnico | geral (padrão: suporte)

Use as ferramentas disponíveis e confirme ao usuário com o número do ticket \
criado. Responda em português."""


# ── LangGraph state ───────────────────────────────────────────────────────────

class State(TypedDict):
    messages: Annotated[list, add_messages]
    agent: str  # "bing" | "search" | "ticket"


# ── Graph factory ─────────────────────────────────────────────────────────────

def create_graph(mcp_tools: list[BaseTool] | None = None):
    """Compile and return the multi-agent LangGraph.

    Args:
        mcp_tools: LangChain tools loaded from the MCP ticket server.
                   When empty the ticket agent still works but without tools
                   (the LLM will explain it cannot register tickets).
    """
    ticket_tools: list[BaseTool] = list(mcp_tools or [])
    bing_tools = [search_products_on_website]
    search_tools = [search_products_in_azure_ai_search]

    def _llm() -> AzureAIOpenAIApiChatModel:
        return AzureAIOpenAIApiChatModel(
            project_endpoint=_FOUNDRY_ENDPOINT,
            credential=DefaultAzureCredential(),
            model=_MODEL_NAME,
            streaming=True,
        )

    base_llm = _llm()
    bing_llm = base_llm.bind_tools(bing_tools)
    search_llm = base_llm.bind_tools(search_tools)
    ticket_llm = base_llm.bind_tools(ticket_tools) if ticket_tools else base_llm

    # ── Nodes ─────────────────────────────────────────────────────────────────

    async def supervisor(state: State) -> dict[str, Any]:
        """Classify intent and select the specialised agent."""
        user_msg = next(
            (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            "",
        )
        resp = await base_llm.ainvoke(
            [SystemMessage(content=_SUPERVISOR_PROMPT), HumanMessage(content=user_msg)]
        )
        raw = resp.content
        if isinstance(raw, list):
            raw = " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in raw)
        raw = raw.strip()
        chosen = raw.lower().split()[0] if raw else "search"
        if chosen not in ("bing", "search", "ticket"):
            chosen = "search"
        logger.info("Supervisor routed to: %s", chosen)
        return {"agent": chosen}

    async def bing_agent(state: State) -> dict[str, Any]:
        msgs = [SystemMessage(content=_BING_PROMPT)] + list(state["messages"])
        return {"messages": [await bing_llm.ainvoke(msgs)]}

    async def search_agent(state: State) -> dict[str, Any]:
        msgs = [SystemMessage(content=_SEARCH_PROMPT)] + list(state["messages"])
        return {"messages": [await search_llm.ainvoke(msgs)]}

    async def ticket_agent(state: State) -> dict[str, Any]:
        msgs = [SystemMessage(content=_TICKET_PROMPT)] + list(state["messages"])
        return {"messages": [await ticket_llm.ainvoke(msgs)]}

    # ── Routing helpers ────────────────────────────────────────────────────────

    def _has_tool_calls(state: State) -> bool:
        last = state["messages"][-1]
        return bool(getattr(last, "tool_calls", None))

    def route_supervisor(state: State) -> str:
        return state["agent"]

    def route_bing(state: State) -> str:
        return "bing_tools" if _has_tool_calls(state) else END

    def route_search(state: State) -> str:
        return "search_tools" if _has_tool_calls(state) else END

    def route_ticket(state: State) -> str:
        if ticket_tools and _has_tool_calls(state):
            return "ticket_tools"
        return END

    # ── Graph ─────────────────────────────────────────────────────────────────

    g = StateGraph(State)

    g.add_node("supervisor", supervisor)
    g.add_node("bing_agent", bing_agent)
    g.add_node("search_agent", search_agent)
    g.add_node("ticket_agent", ticket_agent)
    g.add_node("bing_tools", ToolNode(tools=bing_tools))
    g.add_node("search_tools", ToolNode(tools=search_tools))

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {"bing": "bing_agent", "search": "search_agent", "ticket": "ticket_agent"},
    )

    # Bing loop
    g.add_conditional_edges("bing_agent", route_bing, {"bing_tools": "bing_tools", END: END})
    g.add_edge("bing_tools", "bing_agent")

    # Search loop
    g.add_conditional_edges("search_agent", route_search, {"search_tools": "search_tools", END: END})
    g.add_edge("search_tools", "search_agent")

    # Ticket loop (with or without MCP tools)
    if ticket_tools:
        g.add_node("ticket_tools", ToolNode(tools=ticket_tools))
        g.add_conditional_edges(
            "ticket_agent", route_ticket, {"ticket_tools": "ticket_tools", END: END}
        )
        g.add_edge("ticket_tools", "ticket_agent")
    else:
        g.add_edge("ticket_agent", END)

    return g.compile()
