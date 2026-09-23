"""Web tools: DuckDuckGo search + URL content fetching.

Search uses the DuckDuckGo Instant Answer API (no API key). Fetching
uses `requests` + `beautifulsoup4` (both already installed) to pull a
page and extract its readable text, so the agent can read the full
content behind a search result.

Network calls are gated by the permission system at EXECUTE level so
the user always sees what is being fetched before it happens.
"""

from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

DUCKDUCKGO_API_URL = "https://api.duckduckgo.com/"
DUCKDUCKGO_HTML_URL = "https://duckduckgo.com/?q="
MAX_RESULTS = 8
REQUEST_TIMEOUT_S = 15.0
MAX_FETCH_BYTES = 2_000_000  # refuse to download pages larger than 2 MB
MAX_TEXT_CHARS = 20_000      # cap extracted text returned to the model


class WebSearchTool(Tool):
    """READ/EXECUTE tool: search the web via DuckDuckGo's Instant
    Answer API and return a compact, JSON-serializable list of results.
    """

    name = "web_search"
    description = (
        "Search the web using DuckDuckGo's Instant Answer API. Returns a "
        "compact list of results (title, snippet, url). Use this to look up "
        "documentation, current facts, or anything outside the workspace."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to run against DuckDuckGo.",
            },
            "max_results": {
                "type": "integer",
                "description": f"Maximum number of results to return (default {MAX_RESULTS}).",
            },
        },
        "required": ["query"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"web_search: query DuckDuckGo for '{args.get('query')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        query = args["query"].strip()
        if not query:
            raise ValueError("query must not be empty.")
        max_results = max(1, min(int(args.get("max_results", MAX_RESULTS)), 20))

        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        resp = requests.get(
            DUCKDUCKGO_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": "neo/0.1 (autonomous coding agent)"},
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[dict[str, Any]] = []

        # The Instant Answer "Abstract" is the primary structured result.
        abstract = data.get("AbstractText") or ""
        if abstract:
            results.append(
                {
                    "title": data.get("Heading") or query,
                    "snippet": abstract,
                    "url": data.get("AbstractURL") or "",
                    "type": "abstract",
                }
            )

        # RelatedTopics contains the list of web results.
        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            if "Topics" in topic:
                # A category group; flatten its nested topics.
                for sub in topic["Topics"]:
                    if len(results) >= max_results:
                        break
                    results.append(
                        {
                            "title": sub.get("Text", "").split(" - ")[0],
                            "snippet": sub.get("Text", ""),
                            "url": sub.get("FirstURL", ""),
                            "type": "related",
                        }
                    )
            else:
                results.append(
                    {
                        "title": topic.get("Text", "").split(" - ")[0],
                        "snippet": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                        "type": "related",
                    }
                )

        return {
            "query": query,
            "results": results[:max_results],
            "count": len(results[:max_results]),
            "web_search_url": DUCKDUCKGO_HTML_URL + query.replace(" ", "+"),
        }


class WebFetchTool(Tool):
    """EXECUTE tool: fetch a URL and return its readable text content.

    Uses `requests` to download the page and `beautifulsoup4` to strip
    scripts/styles/navigation and extract the main text, so the agent
    can read the full content behind a search result.
    """

    name = "web_fetch"
    description = (
        "Fetch a URL and return its readable text content (scripts, styles, "
        "and navigation stripped). Use this to read the full page behind a "
        "web_search result."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL (http/https) to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": f"Maximum characters of text to return (default {MAX_TEXT_CHARS}).",
            },
        },
        "required": ["url"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"web_fetch: download and parse '{args.get('url')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        url = args["url"].strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        max_chars = max(500, min(int(args.get("max_chars", MAX_TEXT_CHARS)), 100_000))

        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": "neo/0.1 (autonomous coding agent)"},
        )
        resp.raise_for_status()

        # Guard against huge downloads.
        content = resp.content
        if len(content) > MAX_FETCH_BYTES:
            raise ValueError(f"Page too large ({len(content)} bytes > {MAX_FETCH_BYTES}).")

        # Determine encoding from headers, falling back to apparent encoding.
        if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        html = resp.text

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.get_text(strip=True) if soup.title else ""
        text = soup.get_text(separator="\n", strip=True)
        # Collapse runs of blank lines.
        lines = [ln for ln in text.splitlines() if ln.strip()]
        text = "\n".join(lines)

        truncated = len(text) > max_chars
        return {
            "url": url,
            "title": title,
            "text": text[:max_chars],
            "chars": len(text),
            "truncated": truncated,
        }


def build_web_search_tools() -> list[Tool]:
    """Instantiate the web tools (search + fetch)."""
    return [WebSearchTool(), WebFetchTool()]
