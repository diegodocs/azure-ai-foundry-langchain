"""LangChain tool for web search using DuckDuckGo.

Uses the ``duckduckgo-search`` library to perform web searches.  An optional
site restriction can be applied via the ``WEB_SEARCH_SITE`` environment
variable (e.g., ``paguemenos.com.br``) to restrict results to a single domain.

Environment variables (optional):
    WEB_SEARCH_SITE     Domain to restrict results to, e.g. ``paguemenos.com.br``.
                        When set, ``site:<domain>`` is prepended to every query.
    WEB_SEARCH_COUNT    Max results per query (default: 5).
    WEB_SEARCH_REGION   DuckDuckGo region code (default: br-pt for Brazilian Portuguese).
"""

from __future__ import annotations

import logging
import os

from ddgs import DDGS
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_SITE = os.environ.get("WEB_SEARCH_SITE", "")
_COUNT = int(os.environ.get("WEB_SEARCH_COUNT", os.environ.get("BING_CUSTOM_SEARCH_COUNT", "5")))
_REGION = os.environ.get("WEB_SEARCH_REGION", "br-pt")


# ── LangChain tool ─────────────────────────────────────────────────────────────

@tool
def search_products_on_website(query: str) -> str:
    """Search the web for product and company information.

    Use this tool when the user asks about products, offers, promotions, or
    any content that should be on the company website (pricing, descriptions,
    news, FAQs, store locations, etc.).

    Args:
        query: Natural-language search query.

    Returns:
        Top matching web pages with title, URL, and summary snippet.
    """
    if not query or not query.strip():
        return "No query provided."

    search_query = query.strip()
    if _SITE:
        search_query = f"site:{_SITE} {search_query}"

    try:
        results = DDGS().text(search_query, region=_REGION, max_results=_COUNT)
        if not results:
            return "No results found for the query."

        lines: list[str] = []
        for r in results:
            title = r.get("title", "")
            url = r.get("href", "")
            snippet = r.get("body", "")
            lines.append(f"**{title}**\n{url}\n{snippet}")

        return "\n\n".join(lines)

    except Exception as exc:
        logger.exception("Web search failed")
        return f"Web search error: {type(exc).__name__}: {exc}"
