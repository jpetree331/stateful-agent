"""
Archival memory: curated facts the agent chooses to remember.

Lives in the `archival` schema — separate from conversation history (messages).
Same database, structurally distinct.
"""
from __future__ import annotations

from .db import get_connection


def store_fact(content: str, category: str | None = None) -> tuple[bool, str]:
    """
    Store a fact in archival memory. Returns (success, message).
    """
    content = (content or "").strip()
    if not content:
        return False, "Content cannot be empty"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO archival.facts (content, category)
                VALUES (%s, %s)
                """,
                (content, (category or "").strip() or None),
            )
    return True, "Stored in archival memory"


def query_facts(
    query: str,
    *,
    category: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Query archival facts by text search. Returns list of {content, category, created_at}.
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(limit, 50))
    search = f"%{query}%"

    with get_connection() as conn:
        with conn.cursor() as cur:
            if category:
                cur.execute(
                    """
                    SELECT content, category, created_at
                    FROM archival.facts
                    WHERE (content ILIKE %s OR category ILIKE %s)
                      AND category = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (search, search, category.strip(), limit),
                )
            else:
                cur.execute(
                    """
                    SELECT content, category, created_at
                    FROM archival.facts
                    WHERE content ILIKE %s OR category ILIKE %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (search, search, limit),
                )
            rows = cur.fetchall()

    return [
        {
            "content": row["content"],
            "category": row["category"] or "",
            "created_at": row["created_at"],
        }
        for row in rows
    ]
