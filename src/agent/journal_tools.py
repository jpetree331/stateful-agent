"""
LangChain tools for the journal: save and read entries.

- save_journal_entry: The agent saves full wonder/reflection/research content to the journal.
- read_journal: The agent reads journal entries (its own writings, summaries, user notes).
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def read_journal(
    year_month: str = "",
    entry_date: str = "",
    entry_type: str = "",
    limit: int = 20,
) -> str:
    """
    Read journal entries from the dashboard Journal tab.

    Use this to review your own wonders, reflections, research, summaries,
    heartbeats, or the user's notes. Filter by date and/or type as needed.

    Args:
        year_month: Filter by month as YYYY-MM (e.g. "2026-03"). Omit for recent entries.
        entry_date: Filter by specific day as YYYY-MM-DD. Omit for any day.
        entry_type: Filter by type: 'wonder', 'reflection', 'research', 'summary',
                    'heartbeat', or 'user_note'. Omit for all types.
        limit: Max number of entries to return (default 20, max 50).

    Returns:
        Formatted list of entries with date, type, title, word count, and full content.
    """
    from .journal import is_configured, query_entries

    if not is_configured():
        return "Journal not configured (KNOWLEDGE_DATABASE_URL not set)."

    ym = year_month.strip() or None
    ed = entry_date.strip() or None
    et = entry_type.strip().lower() or None
    try:
        lim = min(max(1, int(limit)), 50)
    except (TypeError, ValueError):
        lim = 20

    entries = query_entries(year_month=ym, entry_date=ed, entry_type=et, limit=lim)

    if not entries:
        filters = []
        if ym:
            filters.append(f"month={ym}")
        if ed:
            filters.append(f"date={ed}")
        if et:
            filters.append(f"type={et}")
        return f"No journal entries found" + (f" for {', '.join(filters)}" if filters else ".")

    lines = []
    for e in entries:
        lines.append(
            f"--- {e['entry_date']} | {e['entry_type']} | {e['title'] or '(untitled)'} | {e['word_count']} words ---"
        )
        lines.append(e["content"])
        lines.append("")

    return "\n".join(lines)


@tool
def save_journal_entry(
    content: str,
    entry_type: str,
    title: str = "",
    entry_date: str = "",
) -> str:
    """
    Save a journal entry (wonder, reflection, research, summary, or heartbeat)
    to the local journal database so it appears in the dashboard Journal tab.

    Call this AFTER writing a wonder, reflection, or research file to disk.
    The full markdown content should be passed here — not just a summary.
    This is how your rich writings become visible in the journal.

    Args:
        content: Full markdown content of the entry (the complete text you wrote).
        entry_type: One of: 'wonder', 'reflection', 'research', 'summary', 'heartbeat'.
                    Use 'wonder' for 1 AM Wonder entries, 'reflection' for 2 AM Reflect,
                    'research' for research sessions, 'summary' for daily summaries,
                    'heartbeat' for general autonomous heartbeat outputs.
        title: Title of the entry (e.g. "On the Ethics of Seeing"). If omitted,
               extracted from the first H1 heading in the content.
        entry_date: Date as YYYY-MM-DD. Defaults to today if not provided.

    Returns:
        Confirmation message with the entry id, or an error message.
    """
    import re
    from datetime import datetime, date
    from zoneinfo import ZoneInfo
    from .journal import is_configured, ensure_schema, _word_count, psycopg_jsonb, _get_connection

    if not is_configured():
        return "Journal not configured (KNOWLEDGE_DATABASE_URL not set) — entry not saved."

    if not content or not content.strip():
        return "Error: content is required."

    valid_types = {"wonder", "reflection", "research", "summary", "heartbeat", "user_note"}
    if entry_type not in valid_types:
        return f"Error: entry_type must be one of {sorted(valid_types)}. Got: {entry_type!r}"

    # Extract title from first H1 if not provided
    if not title:
        h1 = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if h1:
            title = h1.group(1).strip()

    # Parse date
    EST = ZoneInfo("America/New_York")
    now = datetime.now(EST)
    if entry_date:
        try:
            edate = date.fromisoformat(entry_date)
        except ValueError:
            return f"Error: entry_date must be YYYY-MM-DD, got {entry_date!r}"
    else:
        edate = now.date()

    try:
        ensure_schema()
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                # For summaries: upsert (one per day)
                if entry_type == "summary":
                    cur.execute(
                        "SELECT id FROM journal_entries WHERE entry_date = %s AND entry_type = 'summary'",
                        (edate,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE journal_entries
                            SET content = %s, word_count = %s, title = %s, updated_at = %s
                            WHERE id = %s
                            RETURNING id
                            """,
                            (content.strip(), _word_count(content), title or "Daily Summary", now, existing["id"]),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO journal_entries
                                (entry_date, entry_type, title, content, word_count, source, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, 'agent', %s, %s)
                            RETURNING id
                            """,
                            (edate, entry_type, title or "Daily Summary", content.strip(),
                             _word_count(content), now, now),
                        )
                else:
                    cur.execute(
                        """
                        INSERT INTO journal_entries
                            (entry_date, entry_type, title, content, word_count, source, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, 'agent', %s, %s)
                        RETURNING id
                        """,
                        (edate, entry_type, title or entry_type.title(), content.strip(),
                         _word_count(content), now, now),
                    )
                row = cur.fetchone()
            conn.commit()
            entry_id = row["id"] if row else "?"
            wc = _word_count(content)
            return (
                f"Journal entry saved. id={entry_id}, type={entry_type}, "
                f"date={edate}, words={wc}, title={title!r}"
            )
        finally:
            conn.close()
    except Exception as e:
        return f"Error saving journal entry: {e}"
