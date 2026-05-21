"""FastAPI backend — multi-agent chat with SSE streaming.

Endpoints:
  POST /api/chat    — send a message, receive SSE stream
  GET  /api/health  — liveness + MCP status

SSE event types emitted:
  {"type": "session_id",   "session_id": "..."}
  {"type": "agent",        "agent": "bing|search|ticket", "label": "..."}
  {"type": "tool_call",    "tool": "...", "query": "..."}
  {"type": "token",        "content": "..."}
  {"type": "done",         "agent": "..."}
  {"type": "error",        "message": "..."}

Start with:
    python api.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager

# On Windows, the default ProactorEventLoop can crash silently when used with
# SSE streaming responses. Force SelectorEventLoop for stability.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Globals (populated at startup) ────────────────────────────────────────────

_graph = None
_mcp_client = None
_mcp_tool_names: list[str] = []

MCP_TICKET_URL = os.environ.get("MCP_TICKET_SERVER_URL", "http://localhost:8090/sse")
API_PORT = int(os.environ.get("API_PORT", "8088"))

AGENT_LABELS: dict[str, str] = {
    "bing": "Agente Web (Bing)",
    "search": "Agente de Catálogo (AI Search)",
    "ticket": "Agente de Chamados (MCP)",
}

# ── Session store (in-memory) ─────────────────────────────────────────────────

_sessions: dict[str, list] = {}


# ── Lifespan: connect MCP + compile graph ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _mcp_client, _mcp_tool_names

    mcp_tools: list = []
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        _mcp_client = MultiServerMCPClient(
            {"tickets": {"url": MCP_TICKET_URL, "transport": "sse"}}
        )
        # langchain-mcp-adapters ≥0.1.0: get_tools() without context manager
        mcp_tools = await _mcp_client.get_tools()
        _mcp_tool_names = [t.name for t in mcp_tools]
        logger.info("MCP ticket tools loaded: %s", _mcp_tool_names)
    except Exception as exc:
        logger.warning(
            "MCP ticket server not reachable (%s) — ticket agent will work "
            "without tools. Start mcp_ticket_server.py to enable it.",
            exc,
        )

    from agents.supervisor import create_graph

    _graph = create_graph(mcp_tools=mcp_tools)
    logger.info("LangGraph compiled. Agents ready.")

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Multi-Agent Chat API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ── Request / response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    history = _sessions.get(session_id, [])
    messages = list(history) + [HumanMessage(content=req.message)]

    async def stream():
        active_agent = ""
        full_response = ""

        yield _sse({"type": "session_id", "session_id": session_id})

        try:
            async for event in _graph.astream_events(
                {"messages": messages},
                version="v2",
            ):
                kind: str = event["event"]
                node: str = event.get("metadata", {}).get("langgraph_node", "")

                # ── Supervisor finished → announce which agent was selected ──
                if kind == "on_chain_end" and node == "supervisor":
                    output = event.get("data", {}).get("output", {})
                    agent = output.get("agent", "") if isinstance(output, dict) else ""
                    if agent:
                        active_agent = agent
                        yield _sse(
                            {
                                "type": "agent",
                                "agent": agent,
                                "label": AGENT_LABELS.get(agent, agent),
                            }
                        )

                # ── Token streaming from specialised agent nodes only ─────────
                elif kind == "on_chat_model_stream" and node in (
                    "bing_agent",
                    "search_agent",
                    "ticket_agent",
                ):
                    chunk = event["data"]["chunk"]
                    raw = chunk.content
                    if isinstance(raw, list):
                        raw = "".join(
                            c.get("text", "") if isinstance(c, dict) else str(c)
                            for c in raw
                        )
                    if raw:
                        full_response += raw
                        yield _sse({"type": "token", "content": raw})

                # ── Tool invocation indicator ─────────────────────────────────
                elif kind == "on_tool_start":
                    tool_name: str = event.get("name", "")
                    inp = event.get("data", {}).get("input", {})
                    if isinstance(inp, dict):
                        query = inp.get("query") or inp.get("title") or str(inp)[:80]
                    else:
                        query = str(inp)[:80]
                    yield _sse({"type": "tool_call", "tool": tool_name, "query": query})

            # ── Persist turn to session ───────────────────────────────────────
            _sessions[session_id] = messages + [AIMessage(content=full_response)]
            yield _sse({"type": "done", "agent": active_agent})

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Error during graph execution")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "mcp_connected": bool(_mcp_client),
        "mcp_tools": _mcp_tool_names,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        msg = context.get("message", "unknown")
        if exc is not None:
            logger.error("Unhandled asyncio exception: %s", msg, exc_info=exc)
        else:
            logger.error("Unhandled asyncio error: %s", msg)

    async def _set_exception_handler() -> None:
        asyncio.get_event_loop().set_exception_handler(_asyncio_exception_handler)

    logger.info("Starting Multi-Agent API on http://localhost:%d", API_PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=API_PORT,
        loop="asyncio",
    )
