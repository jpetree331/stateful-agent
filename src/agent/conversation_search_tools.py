"""
Conversation search tool: on-demand recall from full PostgreSQL history.

The agent's active context only holds the last ~30 messages. Use this tool
to search the full conversation history when the user references something older.
"""
from __future__ import annotations

from langchain_core.tools import tool

from .db import search_messages
from .hindsight import recall as hindsight_recall_fn, HINDSIGHT_BANK_ID


def _format_results(rows: list[dict]) -> str:
    """Format DB rows into readable snippets with role and date."""
    lines = []
    for row in rows:
        role = row["role"].capitalize()
        dt = row.get("created_at")
        date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "unknown date"
        content = (row["content"] or "").strip()
        # Truncate very long messages to keep output manageable
        if len(content) > 500:
            content = content[:500] + "…"
        lines.append(f"[{role} @ {date_str}]\n{content}")
    return "\n\n".join(lines)


@tool
def conversation_search(query: str, mode: str = "both", limit: int = 10) -> str:
    """
    Search your full conversation history for messages matching a query.

    Your active context only holds the last 30 messages. Use this tool when:
    - The user references something from an older conversation ("remember when...")
    - You need context or details you don't have in the current window
    - You want to check what was said about a specific topic in the past

    Args:
        query: What to search for — keywords, phrases, or a topic.
        mode: Search mode:
              "keyword" — fast exact/substring match in PostgreSQL (best for names, dates, specific phrases)
              "semantic" — Hindsight semantic recall (best for topics, concepts, feelings)
              "both" — runs keyword first; if fewer than 3 results, also runs semantic. (default)
        limit: Max number of results to return (default 10, max 20).
    """
    limit = min(limit, 20)
    results: list[str] = []
    rows: list[dict] = []

    if mode in ("keyword", "both"):
        rows = search_messages(query, limit=limit)
        if rows:
            results.append("--- Keyword matches from conversation history ---")
            results.append(_format_results(rows))

    run_semantic = mode == "semantic" or (mode == "both" and len(rows) < 3)
    if run_semantic:
        semantic = hindsight_recall_fn(bank_id=HINDSIGHT_BANK_ID, query=query)
        if semantic and "don't have any memories" not in semantic and "not available" not in semantic:
            results.append("--- Semantic recall from Hindsight ---")
            results.append(semantic)

    if not results:
        return f"No conversation history found matching '{query}'."

    return "\n\n".join(results)
