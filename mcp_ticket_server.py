"""MCP Ticket Server — runs on localhost:8090 via SSE transport.

Provides three tools:
  - create_ticket : Register a new support ticket
  - list_tickets  : List tickets (optionally filtered by status)
  - close_ticket  : Close an existing ticket

Start with:
    python mcp_ticket_server.py
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("Ticket Server", port=8090)

# ── In-memory store ───────────────────────────────────────────────────────────

_tickets: list[dict[str, Any]] = []
_next_id = 1


# ── Tools ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def create_ticket(
    title: str,
    description: str,
    priority: str = "medium",
    category: str = "support",
) -> dict[str, Any]:
    """Create a new support ticket.

    Args:
        title: Short title summarising the issue (max 80 chars).
        description: Detailed description of the problem or request.
        priority: Urgency level — one of: low, medium, high, critical.
        category: Ticket type — one of: support, billing, technical, general.

    Returns:
        The newly created ticket with id, status and created_at timestamp.
    """
    global _next_id
    ticket: dict[str, Any] = {
        "id": _next_id,
        "title": title[:80],
        "description": description,
        "priority": priority,
        "category": category,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _tickets.append(ticket)
    _next_id += 1
    logger.info("Ticket #%d created: %s", ticket["id"], ticket["title"])
    return ticket


@mcp.tool()
def list_tickets(status: str = "") -> list[dict[str, Any]]:
    """List registered tickets, optionally filtered by status.

    Args:
        status: Filter by status (open, in_progress, closed). Empty = all.

    Returns:
        List of matching ticket objects.
    """
    if status:
        return [t for t in _tickets if t["status"] == status]
    return list(_tickets)


@mcp.tool()
def close_ticket(ticket_id: int, resolution: str = "") -> dict[str, Any]:
    """Close an existing ticket.

    Args:
        ticket_id: Numeric ID of the ticket to close.
        resolution: Optional notes describing how the issue was resolved.

    Returns:
        The updated ticket, or an error dict if not found.
    """
    for ticket in _tickets:
        if ticket["id"] == ticket_id:
            ticket["status"] = "closed"
            ticket["resolved_at"] = datetime.now(timezone.utc).isoformat()
            if resolution:
                ticket["resolution"] = resolution
            logger.info("Ticket #%d closed.", ticket_id)
            return ticket
    return {"error": f"Ticket {ticket_id} not found"}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting MCP Ticket Server on http://localhost:8090 (SSE transport)")
    mcp.run(transport="sse")
