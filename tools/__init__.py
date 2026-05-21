"""Tools package for the langchain-foundry LangGraph agent."""

from tools.ai_search_tool import search_products_in_azure_ai_search
from tools.bing_custom_search_tool import search_products_on_website

TOOLS = [
    search_products_in_azure_ai_search,
    search_products_on_website,
]

__all__ = [
    "search_products_in_azure_ai_search",
    "search_products_on_website",
    "TOOLS",
]
