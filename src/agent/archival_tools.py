"""
Archival memory tools: store and query curated facts.

Separate from conversation history — for facts the agent chooses to remember.
"""
from langchain_core.tools import tool

from .archival import query_facts, store_fact


@tool
def archival_store(content: str, category: str | None = None) -> str:
    """
    Store a fact in your archival memory — things you choose to remember long-term.

    Use when: the user shares something important you want to retain, or you learn a
    fact that should persist beyond the current conversation. This is curated
    memory, not raw chat. Store facts, preferences, decisions, key details.

    Args:
        content: The fact to store (clear, concise).
        category: Optional category (e.g., "preferences", "projects", "family").
    """
    ok, msg = store_fact(content, category)
    return msg if ok else f"Error: {msg}"


@tool
def archival_query(query: str, category: str | None = None) -> str:
    """
    Query your archival memory for facts you've stored.

    Use when: You need to recall something you chose to remember — preferences,
    past decisions, project details, etc. This searches facts you archived, not
    conversation history.

    Args:
        query: What to search for (keywords or phrase).
        category: Optional — limit to a category.
    """
    results = query_facts(query, category=category)
    if not results:
        return "No matching facts in archival memory."
    lines = []
    for r in results:
        cat = f" [{r['category']}]" if r.get("category") else ""
        lines.append(f"- {r['content']}{cat}")
    return "\n".join(lines)
