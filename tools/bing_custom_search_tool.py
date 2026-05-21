"""LangChain tool for web search using Bing Custom Search.

Uses the Bing Custom Search REST API to perform web searches scoped to the
domains configured in the custom search instance. Requires a subscription key
and a configuration ID.

Environment variables:
    BING_CUSTOM_SEARCH_SUBSCRIPTION_KEY  Bing Custom Search API key (required).
    BING_CUSTOM_SEARCH_CONFIG_ID         Custom Search configuration instance ID (required).
    BING_CUSTOM_SEARCH_COUNT             Max results per query (default: 5).
    WEB_SEARCH_SITE                      Optional domain to prepend as ``site:<domain>``
                                         to every query (e.g. ``paguemenos.com.br``).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_SUBSCRIPTION_KEY = os.environ.get("BING_CUSTOM_SEARCH_SUBSCRIPTION_KEY", "")
_CONFIG_ID = os.environ.get("BING_CUSTOM_SEARCH_CONFIG_ID", "")
_COUNT = int(os.environ.get("BING_CUSTOM_SEARCH_COUNT", os.environ.get("WEB_SEARCH_COUNT", "5")))
_SITE = os.environ.get("WEB_SEARCH_SITE", "")
_BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/custom/search"


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

    if not _SUBSCRIPTION_KEY or not _CONFIG_ID:
        logger.warning("BING_CUSTOM_SEARCH_SUBSCRIPTION_KEY or BING_CUSTOM_SEARCH_CONFIG_ID not configured.")
        return "Web search is not configured (missing Bing credentials)."

    search_query = query.strip()
    if _SITE:
        search_query = f"site:{_SITE} {search_query}"

    params = urllib.parse.urlencode({
        "q": search_query,
        "customconfig": _CONFIG_ID,
        "count": _COUNT,
        "mkt": "pt-BR",
    })
    req = urllib.request.Request(
        f"{_BING_ENDPOINT}?{params}",
        headers={"Ocp-Apim-Subscription-Key": _SUBSCRIPTION_KEY},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        results = data.get("webPages", {}).get("value", [])
        if not results:
            return "No results found for the query."

        lines: list[str] = []
        for r in results:
            title = r.get("name", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            lines.append(f"**{title}**\n{url}\n{snippet}")

        return "\n\n".join(lines)

    except Exception as exc:
        logger.exception("Bing Custom Search failed")
        return f"Web search error: {type(exc).__name__}: {exc}"
