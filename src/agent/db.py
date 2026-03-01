"""
PostgreSQL conversation history (DB 1).

Stores full user and assistant messages with metadata.
Timestamps are stored in UTC; metadata includes date/time in EST.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

EST = ZoneInfo("America/New_York")

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    reasoning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    UNIQUE(thread_id, idx)
)
"""
INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id)"
ADD_REASONING_SQL = "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reasoning TEXT"
# Allow 'tool' role for tool return messages (Hindsight, etc.)
ADD_TOOL_ROLE_SQL = """
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_role_check;
ALTER TABLE messages ADD CONSTRAINT messages_role_check
  CHECK (role IN ('user', 'assistant', 'tool'));
"""


def get_connection_string() -> str:
    """Get Postgres connection string from env."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError(
            "DATABASE_URL is required. Set it in .env (e.g. from Railway)."
        )
    return url


def check_connection() -> bool:
    """Verify DB connection. Returns True if OK, raises on failure."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return True


def _open_connection(retries: int = 2, delay: float = 2.0):
    """Open a Postgres connection, retrying on OperationalError (e.g. Railway drops)."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return psycopg.connect(get_connection_string(), row_factory=dict_row)
        except psycopg.OperationalError as e:
            last_exc = e
            if attempt < retries:
                logger.warning(
                    f"DB connection failed (attempt {attempt + 1}/{retries + 1}), "
                    f"retrying in {delay:.0f}s: {e}"
                )
                time.sleep(delay)
    raise last_exc


@contextmanager
def get_connection():
    """Context manager for a Postgres connection with retry on connect failure."""
    conn = _open_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def setup_schema() -> None:
    """Create messages and core_memory tables if they don't exist."""
    with get_connection() as conn:
        conn.execute(TABLE_SQL)
        conn.execute(INDEX_SQL)
        conn.execute(ADD_REASONING_SQL)
        conn.execute(ADD_TOOL_ROLE_SQL)
        # Core memory blocks (user, identity, ideaspace)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_memory (
                block_type TEXT PRIMARY KEY CHECK (block_type IN ('user', 'identity', 'ideaspace')),
                content TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_memory_history (
                id SERIAL PRIMARY KEY,
                block_type TEXT NOT NULL,
                content TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # Read-only system instructions (agent cannot edit)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_instructions (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                content TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.execute(
            "INSERT INTO system_instructions (id, content) VALUES (1, '') ON CONFLICT (id) DO NOTHING"
        )
        # Archival memory: separate schema for curated facts (not raw conversation)
        conn.execute("CREATE SCHEMA IF NOT EXISTS archival")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archival.facts (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB DEFAULT '{}'
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_archival_facts_category ON archival.facts(category)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_archival_facts_created ON archival.facts(created_at DESC)"
        )
        # Cron jobs for scheduled tasks
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                instructions TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'America/New_York',
                schedule_days INTEGER[],
                schedule_time TEXT,
                run_date DATE,
                is_one_time BOOLEAN NOT NULL DEFAULT FALSE,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
                created_by TEXT NOT NULL DEFAULT 'user' CHECK (created_by IN ('user', 'agent')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_run_at TIMESTAMPTZ,
                last_run_status TEXT CHECK (last_run_status IN ('success', 'error', 'skipped', 'aborted')),
                last_run_error TEXT,
                run_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cron_jobs_status ON cron_jobs(status)"
        )
        # Add new columns for one-time jobs (migration)
        conn.execute("ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS run_date DATE")
        conn.execute("ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS is_one_time BOOLEAN NOT NULL DEFAULT FALSE")
        # Make schedule_days and schedule_time nullable for one-time jobs
        conn.execute("ALTER TABLE cron_jobs ALTER COLUMN schedule_days DROP NOT NULL")
        conn.execute("ALTER TABLE cron_jobs ALTER COLUMN schedule_time DROP NOT NULL")
        # Daily summaries: the agent writes a short summary of each day for persistent temporal context
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_summaries (
                id SERIAL PRIMARY KEY,
                summary_date DATE NOT NULL UNIQUE,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def _format_metadata(created_at) -> dict:
    """Build metadata with EST date/time."""
    dt_est = created_at.astimezone(EST)
    return {
        "date_est": dt_est.strftime("%Y-%m-%d"),
        "time_est": dt_est.strftime("%H:%M:%S %Z"),
    }


def load_messages(
    thread_id: str,
    *,
    limit: int | None = None,
    since=None,
    max_tokens: int | None = None,
    include_metadata: bool = True,
    exclude_tool_messages: bool = True,
    exclude_heartbeat: bool = False,
) -> list[dict]:
    """
    Load conversation history for a thread.

    Applies a "today OR last N, whichever covers more" window:
    - `since`: a timezone-aware datetime marking start of "today" (e.g. midnight EST).
      All messages on or after this timestamp are always included.
    - `limit`: minimum number of recent messages to include (the floor).
    - The effective window starts at whichever boundary is earlier — so a busy day
      never drops same-day context, and a quiet day still has at least `limit` messages.
    - `max_tokens`: final token-count safety cap (applied after the window).
    - `exclude_heartbeat`: if True, heartbeat user messages AND their assistant responses
      are excluded — both carry metadata role_display='heartbeat'. Use this for regular
      chat context; the daily summary captures what happened during heartbeats instead.

    Tool messages are excluded by default — they are noisy, expensive, and not
    useful for recent context (they were tool call returns, not conversation).

    Returns list of dicts with: role, content, reasoning (optional), created_at, metadata.
    Ordered by idx ascending.
    """
    filters = []
    if exclude_tool_messages:
        filters.append("role != 'tool'")
    if exclude_heartbeat:
        filters.append(
            "(metadata->>'role_display' IS NULL OR metadata->>'role_display' != 'heartbeat')"
        )
    role_filter = ("AND " + " AND ".join(filters)) if filters else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, thread_id, idx, role, content, reasoning, created_at, metadata
                FROM messages
                WHERE thread_id = %s {role_filter}
                ORDER BY idx ASC
                """,
                (thread_id,),
            )
            rows = cur.fetchall()

    out = []
    for row in rows:
        meta = dict(row.get("metadata") or {})
        if include_metadata:
            meta.update(_format_metadata(row["created_at"]))
        out.append({
            "role": row["role"],
            "content": row["content"],
            "reasoning": row.get("reasoning"),
            "created_at": row["created_at"],
            "metadata": meta,
        })

    if limit is not None or since is not None:
        # Find where "today" starts (first message on or after `since`)
        today_start = len(out)  # default: no today messages
        if since is not None:
            for i, row in enumerate(out):
                if row["created_at"] >= since:
                    today_start = i
                    break

        # Find where "last N" starts
        last_n_start = max(0, len(out) - limit) if limit is not None else len(out)

        # Take whichever boundary is earlier — more messages, not fewer
        out = out[min(today_start, last_n_start):]

    if max_tokens and max_tokens > 0:
        out = _trim_to_token_limit(out, max_tokens)

    return out


def _trim_to_token_limit(rows: list[dict], max_tokens: int) -> list[dict]:
    """Keep most recent messages that fit within max_tokens (sliding window)."""
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
    except Exception:
        enc = None

    def count_tokens(text: str) -> int:
        if enc:
            return len(enc.encode(text))
        return len(text) // 4  # Fallback: ~4 chars per token

    total = 0
    result = []
    for row in reversed(rows):
        text = row["content"] or ""
        if row.get("reasoning"):
            text = f"[Reasoning: {row['reasoning']}]\n\n{text}"
        tokens = count_tokens(text)
        if total + tokens > max_tokens and result:
            break
        result.insert(0, row)
        total += tokens

    return result


def search_messages(
    query: str,
    *,
    thread_id: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Keyword search over conversation history using PostgreSQL ILIKE.

    Searches user and assistant messages only (not tool messages).
    Returns list of dicts with: role, content, created_at, metadata.
    Ordered by idx descending (most recent first).

    Args:
        query: Search term (case-insensitive substring match).
        thread_id: Limit to a specific thread (default: all threads).
        limit: Maximum number of results to return.
    """
    params: list = [f"%{query}%", limit]
    thread_clause = ""
    if thread_id:
        thread_clause = "AND thread_id = %s"
        params = [f"%{query}%", thread_id, limit]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT idx, role, content, created_at, metadata
                FROM messages
                WHERE content ILIKE %s
                  AND role IN ('user', 'assistant')
                  {thread_clause}
                ORDER BY idx DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    out = []
    for row in rows:
        meta = dict(row.get("metadata") or {})
        out.append({
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
            "metadata": meta,
        })
    return out


def append_messages(
    thread_id: str,
    messages: list[tuple[str, str, dict | None, str | None]],
    *,
    user_display_name: str | None = None,
) -> None:
    """
    Append messages to a thread.

    Args:
        thread_id: Thread identifier.
        messages: List of (role, content, metadata_extra, reasoning) tuples.
                  role is 'user' or 'assistant'.
                  metadata_extra is optional dict merged into metadata.
                  reasoning is optional, for assistant messages only.
        user_display_name: If set, stored in metadata for user messages
                          (custom label instead of "user").
    """
    if not messages:
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(idx), -1) + 1 AS next_idx FROM messages WHERE thread_id = %s",
                (thread_id,),
            )
            row = cur.fetchone()
            next_idx = row["next_idx"] if row else 0

            for item in messages:
                if len(item) == 3:
                    role, content, meta_extra = item[0], item[1], item[2]
                    reasoning = None
                else:
                    role, content, meta_extra, reasoning = item[0], item[1], item[2], item[3]

                metadata = dict(meta_extra or {})
                if role == "user" and user_display_name:
                    metadata["role_display"] = user_display_name

                cur.execute(
                    """
                    INSERT INTO messages (thread_id, idx, role, content, reasoning, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (thread_id, next_idx, role, content, reasoning, Jsonb(metadata)),
                )
                next_idx += 1


# === Daily Summaries ===

def upsert_daily_summary(summary_date: str, content: str) -> dict:
    """
    Write or overwrite the summary for a given date.

    Args:
        summary_date: ISO date string 'YYYY-MM-DD'
        content: The summary text written by the agent
    Returns:
        The saved row as a dict
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_summaries (summary_date, content, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (summary_date) DO UPDATE
                  SET content = EXCLUDED.content,
                      updated_at = NOW()
                RETURNING id, summary_date, content, created_at, updated_at
                """,
                (summary_date, content),
            )
            row = cur.fetchone()
            return dict(row)


def load_daily_summaries(days: int = 7) -> list[dict]:
    """
    Load the most recent N daily summaries, newest first.

    Args:
        days: How many summaries to load (default 7)
    Returns:
        List of dicts with keys: summary_date, content
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT summary_date, content
                FROM daily_summaries
                ORDER BY summary_date DESC
                LIMIT %s
                """,
                (days,),
            )
            rows = cur.fetchall()
    return [{"summary_date": row["summary_date"].isoformat(), "content": row["content"]} for row in rows]
