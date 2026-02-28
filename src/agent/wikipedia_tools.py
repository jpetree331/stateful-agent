"""
Wikipedia lookup tool.

Uses the public Wikipedia REST API — no API key, no extra packages.
httpx is already a project dependency.

Two-step process:
  1. Search Wikipedia for the best matching article title
  2. Fetch the intro summary (first few paragraphs) of that article

Use for fast, reliable factual lookups: biographies, concepts, history,
geography, science — anything encyclopedic. Much faster than a full web_search
for topics that have a Wikipedia article.
"""
from __future__ import annotations

import httpx
from langchain_core.tools import tool

_TIMEOUT = 10
_WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
_WIKI_API = "https://en.wikipedia.org/w/api.php"


def _search_wikipedia(query: str, limit: int = 3) -> list[dict]:
    """Return top matching article titles and snippets."""
    resp = httpx.get(
        _WIKI_API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "utf8": 1,
        },
        headers={"User-Agent": "LangGraphAgent/1.0 (personal assistant)"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("query", {}).get("search", [])


def _fetch_summary(title: str) -> dict:
    """Fetch the intro summary for a Wikipedia article by exact title."""
    import urllib.parse
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    resp = httpx.get(
        f"{_WIKI_REST}/page/summary/{encoded}",
        headers={"User-Agent": "LangGraphAgent/1.0 (personal assistant)"},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json()


@tool
def wikipedia_lookup(query: str) -> str:
    """
    Look up a topic on Wikipedia and return a clear factual summary.

    Best for: biographies, historical events, scientific concepts, places,
    organisations, terminology — anything with a Wikipedia article.
    Much faster than a web search for encyclopedic facts.

    Examples: "Marie Curie", "French Revolution", "quantum entanglement",
              "Python programming language", "Buenos Aires"

    Args:
        query: The topic or question to look up.
    """
    # Step 1: search for best matching article
    try:
        search_results = _search_wikipedia(query, limit=3)
    except Exception as e:
        return f"Wikipedia search failed: {e}"

    if not search_results:
        return f"No Wikipedia article found for '{query}'."

    # Step 2: fetch full summary for the top result
    top_title = search_results[0]["title"]
    try:
        data = _fetch_summary(top_title)
    except httpx.HTTPStatusError as e:
        # If top result 404s, try the second result
        if e.response.status_code == 404 and len(search_results) > 1:
            try:
                data = _fetch_summary(search_results[1]["title"])
                top_title = search_results[1]["title"]
            except Exception as e2:
                return f"Wikipedia fetch failed: {e2}"
        else:
            return f"Wikipedia fetch failed ({e.response.status_code}) for '{top_title}'."
    except Exception as e:
        return f"Wikipedia fetch failed: {e}"

    title = data.get("title", top_title)
    description = data.get("description", "")
    extract = data.get("extract", "").strip()
    page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

    lines = [f"=== Wikipedia: {title} ==="]
    if description:
        lines.append(f"({description})\n")
    if extract:
        lines.append(extract)
    if page_url:
        lines.append(f"\nSource: {page_url}")

    # Show alternate results if the match might not be what was intended
    if len(search_results) > 1:
        alts = [r["title"] for r in search_results[1:]]
        lines.append(f"\nOther possible matches: {', '.join(alts)}")

    return "\n".join(lines)
