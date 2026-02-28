"""
Web search tools: Brave (general), Exa (research/semantic), Tavily (AI-summarised).

- Brave Search: fast, broad results for news, facts, current events.
- Exa: semantic search returning actual page text for deep research.
- Tavily: purpose-built for AI agents; returns a synthesised answer + clean sources.
  Free tier: 1,000 API calls/month. Great default when you want a direct answer.

All modes live in one `web_search` tool so the agent has a single thing to reason about.

Required env vars (add whichever providers you sign up for):
  BRAVE_API_KEY   — https://brave.com/search/api/
  EXA_API_KEY     — https://exa.ai
  TAVILY_API_KEY  — https://app.tavily.com  (free 1k/month tier available)
"""
from __future__ import annotations

import os

import httpx
from langchain_core.tools import tool

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

_TIMEOUT = 15  # seconds


def _brave_search(query: str, count: int) -> list[dict]:
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count},
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("web", {}).get("results", [])
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in results
    ]


def _exa_search(query: str, num_results: int) -> list[dict]:
    resp = httpx.post(
        "https://api.exa.ai/search",
        json={"query": query, "numResults": num_results, "contents": {"text": {"maxCharacters": 1500}}},
        headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "text": (r.get("text") or "")[:1200]}
        for r in results
    ]


def _tavily_search(query: str, num_results: int) -> dict:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": num_results,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@tool
def web_search(query: str, mode: str = "tavily", num_results: int = 5) -> str:
    """
    Search the web for current information, news, facts, or research.

    Use whenever you need information beyond your training data or want to verify
    something current. Default to this before saying "I don't know."

    Args:
        query: What to search for. Be specific for better results.
        mode: "tavily"   — AI-synthesised answer + clean sources. Best default for most queries.
                           Returns a direct answer, not just links. Free tier available.
              "general"  — Brave Search. Fast and broad. Best for news, current events,
                           product info, or when you want many source links quickly.
              "research" — Exa semantic search. Returns actual page text. Best for deep dives,
                           academic/technical topics where you want to read the content itself.
        num_results: How many results to return (default 5, max 10).
    """
    num_results = min(int(num_results), 10)

    if mode == "tavily":
        if not TAVILY_API_KEY:
            return "Error: TAVILY_API_KEY not configured in .env (get free key at app.tavily.com)"
        try:
            data = _tavily_search(query, num_results)
        except httpx.HTTPStatusError as e:
            return f"Tavily error {e.response.status_code}: {e.response.text[:300]}"
        except Exception as e:
            return f"Tavily search failed: {e}"

        lines = [f"=== Tavily: {query} ===\n"]
        answer = data.get("answer")
        if answer:
            lines.append(f"**Answer:** {answer}\n")
        results = data.get("results", [])
        if results:
            lines.append("**Sources:**")
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title', '')}  —  {r.get('url', '')}")
                snippet = (r.get("content") or "")[:400]
                if snippet:
                    lines.append(f"   {snippet}")
        return "\n".join(lines)

    elif mode == "research":
        if not EXA_API_KEY:
            return "Error: EXA_API_KEY not configured in .env"
        try:
            results = _exa_search(query, num_results)
        except httpx.HTTPStatusError as e:
            return f"Exa error {e.response.status_code}: {e.response.text[:300]}"
        except Exception as e:
            return f"Exa search failed: {e}"

        if not results:
            return f"No research results for '{query}'."
        lines = [f"=== Exa Research: {query} ===\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**\n   {r['url']}")
            if r["text"]:
                lines.append(f"   {r['text']}\n")
        return "\n".join(lines)

    else:  # general / Brave
        if not BRAVE_API_KEY:
            return "Error: BRAVE_API_KEY not configured in .env"
        try:
            results = _brave_search(query, num_results)
        except httpx.HTTPStatusError as e:
            return f"Brave error {e.response.status_code}: {e.response.text[:300]}"
        except Exception as e:
            return f"Brave search failed: {e}"

        if not results:
            return f"No results for '{query}'."
        lines = [f"=== Brave Search: {query} ===\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**\n   {r['url']}")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines)
