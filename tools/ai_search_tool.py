"""LangChain tool for Azure AI Search — hybrid keyword + vector search.

Uses the ``azure-search-documents`` SDK with DefaultAzureCredential (Managed
Identity / Entra ID) by default.  Falls back to an API key when
``AZURE_SEARCH_API_KEY`` is set in the environment.

Environment variables (all required unless noted):
    AZURE_SEARCH_ENDPOINT       Full URL of the Azure AI Search service.
    AZURE_SEARCH_INDEX_NAME     Name of the langchain-foundry index.
    AZURE_SEARCH_API_KEY        API key (optional; prefer Managed Identity).
    AZURE_SEARCH_CONTENT_FIELD  Name of the text content field (default: content).
    AZURE_SEARCH_SELECT_FIELDS  Comma-separated fields to return (optional).
    AZURE_SEARCH_TOP            Max results per query (default: 5).
"""

from __future__ import annotations

import logging
import os

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
_INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", "langchain-foundry")
_API_KEY = os.environ.get("AZURE_SEARCH_API_KEY", "")
_CONTENT_FIELD = os.environ.get("AZURE_SEARCH_CONTENT_FIELD", "content")
_SELECT_FIELDS = os.environ.get("AZURE_SEARCH_SELECT_FIELDS", "")
_TOP = int(os.environ.get("AZURE_SEARCH_TOP", "5"))
_VECTOR_FIELD = os.environ.get("AZURE_SEARCH_VECTOR_FIELD", "contentVector")


def _build_client() -> SearchClient:
    """Create an authenticated SearchClient.

    Prefers API-key authentication when ``AZURE_SEARCH_API_KEY`` is set so
    that local development works without Entra ID role assignments.  In hosted
    Foundry containers the Managed Identity provided by ``DefaultAzureCredential``
    is used automatically (no API key needed).
    """
    if not _ENDPOINT:
        raise EnvironmentError(
            "AZURE_SEARCH_ENDPOINT is not set. "
            "Set it to the URL of your Azure AI Search service."
        )

    credential: AzureKeyCredential | DefaultAzureCredential
    if _API_KEY:
        credential = AzureKeyCredential(_API_KEY)
    else:
        credential = DefaultAzureCredential()

    return SearchClient(
        endpoint=_ENDPOINT,
        index_name=_INDEX_NAME,
        credential=credential,
    )


# Build client once at module load (fails fast on bad config).
_client = _build_client()

# Track whether vector search has been confirmed unsupported (avoids repeated warnings).
_vector_search_disabled = False


def _format_result(result: dict) -> str:
    """Render a single search hit as a readable text snippet."""
    parts: list[str] = []

    # Title / ID header
    title = result.get("title") or result.get("id") or "—"
    parts.append(f"[{title}]")

    # Main content field
    content = result.get(_CONTENT_FIELD) or ""
    if content:
        # Truncate very long chunks to keep context window manageable.
        parts.append(content[:2000])

    # Extra metadata fields the caller configured
    meta_fields = [f for f in result.keys() if f not in {"title", "id", _CONTENT_FIELD}]
    for field in meta_fields:
        value = result.get(field)
        if value:
            parts.append(f"{field}: {value}")

    return "\n".join(parts)


@tool
def search_products_in_azure_ai_search(query: str) -> str:
    """Search the product catalog using Azure AI Search (hybrid search).

    Use this tool whenever the user asks about specific products, features,
    prices, categories, or any information likely to be found in the indexed
    product documents.

    Args:
        query: Natural-language search query about products.

    Returns:
        Top matching product information formatted as readable text.
    """
    if not query or not query.strip():
        return "No query provided."

    select_fields: list[str] | None = (
        [f.strip() for f in _SELECT_FIELDS.split(",") if f.strip()]
        if _SELECT_FIELDS
        else None
    )

    # ── 1. Try hybrid search (text + vector) ─────────────────────────────────
    global _vector_search_disabled
    if not _vector_search_disabled:
        try:
            vector_query = VectorizableTextQuery(
                text=query,
                k_nearest_neighbors=_TOP,
                fields=_VECTOR_FIELD,
            )
            results = _client.search(
                search_text=query,
                vector_queries=[vector_query],
                select=select_fields,
                top=_TOP,
            )
            hits = [_format_result(dict(r)) for r in results]
            if hits:
                return f"Found {len(hits)} product(s) in the catalog:\n" + "\n---\n".join(hits)
        except Exception as exc:
            _vector_search_disabled = True
            logger.warning(
                "Hybrid search not available (%s) — switching permanently to keyword-only search.",
                exc,
            )

    # ── 2. Fallback: keyword-only search ─────────────────────────────────────
    try:
        results = _client.search(
            search_text=query,
            select=select_fields,
            top=_TOP,
        )
        hits = [_format_result(dict(r)) for r in results]
        if not hits:
            return "No products found matching your query in the catalog."
        return f"Found {len(hits)} product(s) in the catalog:\n" + "\n---\n".join(hits)
    except Exception as exc:
        logger.exception("Azure AI Search keyword query failed")
        return f"Azure AI Search error: {type(exc).__name__}: {exc}"
