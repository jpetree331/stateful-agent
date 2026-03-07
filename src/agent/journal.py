"""
Journal: unified daily log of the agent's outputs and user notes.

Stores in local PostgreSQL (rowan-data, same DB as Knowledge Bank).
Tables: journal_entries

Entry types:
  'wonder'      — 1 AM Wonder heartbeat output
  'reflection'  — 2 AM Reflect heartbeat output
  'research'    — research heartbeat output (any topic)
  'summary'     — daily summary written by the agent
  'user_note'   — journal note written by the user
  'heartbeat'   — generic heartbeat output (fallback if type undetected)

Conversation history is NOT stored here — it's queried live from Railway Postgres.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id SERIAL PRIMARY KEY,
    entry_date DATE NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN (
        'wonder', 'reflection', 'research', 'summary', 'user_note', 'heartbeat'
    )),
    title TEXT,
    content TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'system',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON journal_entries(entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_journal_entries_type ON journal_entries(entry_type);
"""


def _get_connection():
    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not url:
        raise ValueError("KNOWLEDGE_DATABASE_URL not set — journal uses local Postgres.")
    import psycopg
    return psycopg.connect(url, row_factory=psycopg.rows.dict_row)


def ensure_schema() -> None:
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            for stmt in _SCHEMA_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _detect_heartbeat_type(content: str, cron_name: str | None = None) -> tuple[str, str | None]:
    """
    Detect entry type and title from heartbeat content or cron job name.
    Returns (entry_type, title).

    Cron name patterns handled:
      "1 AM Wonder"                          → wonder
      "2 AM Reflection"                      → reflection
      "GitHub Stateful Agents Research - Thursday" → research, title = "Github Stateful Agents Research"
      "Weekly Summary"                       → summary
      "Daily Summary"                        → summary
      Anything else                          → heartbeat (generic), title = cron_name
    """
    name = (cron_name or "").lower().strip()
    raw_name = (cron_name or "").strip()
    text = content.lower()[:500]

    # Strip trailing day-of-week suffix for cleaner titles, e.g. "Research Topic - Thursday"
    clean_name = re.sub(
        r"\s*[-–]\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        "", raw_name, flags=re.I
    ).strip()

    if "wonder" in name:
        return "wonder", clean_name or "Wonder"
    if "reflect" in name:
        return "reflection", clean_name or "Reflection"
    if "research" in name:
        return "research", clean_name or "Research"
    if "summary" in name or "summarize" in name:
        return "summary", clean_name or "Daily Summary"

    # Fallback: detect from content keywords
    if any(w in text for w in ["wonder", "curious", "what if", "i wonder"]):
        return "wonder", clean_name or "Wonder"
    if any(w in text for w in ["reflect", "reflection", "looking back", "i've been thinking"]):
        return "reflection", clean_name or "Reflection"
    if any(w in text for w in ["research", "found that", "according to", "studied", "i researched"]):
        return "research", clean_name or "Research"
    if any(w in text for w in ["today i", "daily summary", "summary of today", "this week"]):
        return "summary", clean_name or "Summary"

    return "heartbeat", clean_name or cron_name or "Heartbeat"


def save_heartbeat_output(
    content: str,
    cron_name: str | None = None,
    entry_date: date | None = None,
    created_at: datetime | None = None,
) -> int | None:
    """
    Save a heartbeat output to the journal. Returns new entry id or None on error.
    Skips HEARTBEAT_OK (no-op responses).
    """
    if not content or content.strip().upper() == "HEARTBEAT_OK":
        return None
    if not is_configured():
        return None

    entry_type, title = _detect_heartbeat_type(content, cron_name)
    now = created_at or datetime.now(EST)
    edate = entry_date or now.date()

    try:
        ensure_schema()
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (entry_date, entry_type, title, content, word_count, source, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'heartbeat', %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        edate,
                        entry_type,
                        title,
                        content.strip(),
                        _word_count(content),
                        psycopg_jsonb({"cron_name": cron_name}),
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
            return row["id"] if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.save_heartbeat_output failed: %s", e)
        return None


def save_daily_summary(
    summary_date: str,
    content: str,
    created_at: datetime | None = None,
) -> int | None:
    """
    Save or update a daily summary in the journal.
    Uses upsert on (entry_date, entry_type='summary') — one summary per day.
    Returns entry id or None on error.
    """
    if not is_configured():
        return None
    try:
        ensure_schema()
        edate = date.fromisoformat(summary_date)
        now = created_at or datetime.now(EST)
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                # Upsert: update if a summary already exists for this date
                # Check if a summary already exists for this date
                cur.execute(
                    "SELECT id FROM journal_entries WHERE entry_date = %s AND entry_type = 'summary'",
                    (edate,),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """
                        UPDATE journal_entries
                        SET content = %s, word_count = %s, updated_at = %s, title = 'Daily Summary'
                        WHERE id = %s
                        RETURNING id
                        """,
                        (content.strip(), _word_count(content), now, existing["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO journal_entries
                            (entry_date, entry_type, title, content, word_count, source, created_at, updated_at)
                        VALUES (%s, 'summary', 'Daily Summary', %s, %s, 'daily_summary', %s, %s)
                        RETURNING id
                        """,
                        (edate, content.strip(), _word_count(content), now, now),
                    )
                row = cur.fetchone()
            conn.commit()
            return row["id"] if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.save_daily_summary failed: %s", e)
        return None


def save_user_note(
    content: str,
    title: str | None = None,
    entry_date: date | None = None,
) -> int | None:
    """Save a user-written journal note. Returns entry id or None on error."""
    if not is_configured():
        return None
    try:
        ensure_schema()
        now = datetime.now(EST)
        edate = entry_date or now.date()
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (entry_date, entry_type, title, content, word_count, source, created_at, updated_at)
                    VALUES (%s, 'user_note', %s, %s, %s, 'user', %s, %s)
                    RETURNING id
                    """,
                    (edate, title or "Note", content.strip(), _word_count(content), now, now),
                )
                row = cur.fetchone()
            conn.commit()
            return row["id"] if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.save_user_note failed: %s", e)
        return None


def get_months_with_entries() -> list[str]:
    """Return list of 'YYYY-MM' strings that have journal entries or daily summaries, newest first."""
    if not is_configured():
        return []
    try:
        ensure_schema()
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT TO_CHAR(entry_date, 'YYYY-MM') AS month
                    FROM journal_entries
                    ORDER BY month DESC
                    """
                )
                rows = cur.fetchall()
            return [r["month"] for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.get_months_with_entries failed: %s", e)
        return []


def get_entries_for_month(year_month: str) -> list[dict]:
    """
    Return all journal entries for a given month (YYYY-MM), grouped by date.
    Returns list of day dicts: {date, entries: [...]}
    Entries sorted by created_at DESC within each day (most recent first). Days sorted newest first.
    """
    if not is_configured():
        return []
    try:
        ensure_schema()
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, entry_date, entry_type, title, content, word_count,
                           source, metadata, created_at, updated_at
                    FROM journal_entries
                    WHERE TO_CHAR(entry_date, 'YYYY-MM') = %s
                    ORDER BY entry_date DESC, created_at DESC
                    """,
                    (year_month,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        # Group by date
        days: dict[str, list] = {}
        for r in rows:
            d = r["entry_date"].isoformat()
            if d not in days:
                days[d] = []
            days[d].append({
                "id": r["id"],
                "entry_type": r["entry_type"],
                "title": r["title"],
                "content": r["content"],
                "word_count": r["word_count"],
                "source": r["source"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            })

        return [{"date": d, "entries": entries} for d, entries in sorted(days.items(), reverse=True)]
    except Exception as e:
        logger.warning("journal.get_entries_for_month failed: %s", e)
        return []


def query_entries(
    year_month: str | None = None,
    entry_date: str | None = None,
    entry_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Query journal entries with optional filters.
    Returns list of dicts: id, entry_date, entry_type, title, content, word_count, created_at.
    """
    if not is_configured():
        return []
    valid_types = {"wonder", "reflection", "research", "summary", "heartbeat", "user_note"}
    if entry_type and entry_type not in valid_types:
        return []
    try:
        ensure_schema()
        conn = _get_connection()
        try:
            conditions = []
            params = []
            if year_month:
                conditions.append("TO_CHAR(entry_date, 'YYYY-MM') = %s")
                params.append(year_month)
            if entry_date:
                conditions.append("entry_date = %s")
                params.append(entry_date)
            if entry_type:
                conditions.append("entry_type = %s")
                params.append(entry_type)
            where = " AND ".join(conditions) if conditions else "TRUE"
            params.append(limit)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, entry_date, entry_type, title, content, word_count, created_at
                    FROM journal_entries
                    WHERE {where}
                    ORDER BY entry_date DESC, created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "entry_date": r["entry_date"].isoformat(),
                    "entry_type": r["entry_type"],
                    "title": r["title"],
                    "content": r["content"],
                    "word_count": r["word_count"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.query_entries failed: %s", e)
        return []


def update_user_note(entry_id: int, content: str, title: str | None = None, append: bool = False) -> bool:
    """
    Update a user journal note. Returns True if updated.
    If append=True, appends content to existing; otherwise replaces.
    """
    if not is_configured():
        return False
    try:
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, content, title FROM journal_entries WHERE id = %s AND entry_type = 'user_note'",
                    (entry_id,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                new_content = (row["content"] + "\n\n" + content.strip()) if append else content.strip()
                new_title = title if title is not None else row["title"]
                cur.execute(
                    """
                    UPDATE journal_entries
                    SET content = %s, title = %s, word_count = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (new_content, new_title, _word_count(new_content), entry_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.update_user_note failed: %s", e)
        return False


def delete_entry(entry_id: int) -> bool:
    """Delete a journal entry by id. Returns True if deleted."""
    if not is_configured():
        return False
    try:
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM journal_entries WHERE id = %s", (entry_id,))
                deleted = cur.rowcount
            conn.commit()
            return deleted > 0
        finally:
            conn.close()
    except Exception as e:
        logger.warning("journal.delete_entry failed: %s", e)
        return False


def is_configured() -> bool:
    return bool(os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip())


def psycopg_jsonb(data: dict):
    """Wrap dict as psycopg Jsonb for insertion."""
    try:
        from psycopg.types.json import Jsonb
        return Jsonb(data)
    except Exception:
        import json
        return json.dumps(data)
