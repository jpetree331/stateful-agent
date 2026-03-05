"""
Living Logs tools — structured agent-authored records that build the agent's inner life.

Five tables in the main PostgreSQL database:
  tension_log        — friction, value conflicts, errors, hesitation
  loose_threads      — open questions and unresolved intellectual threads
  evolving_positions — longitudinal intellectual identity (one row per topic, UPSERT)
  shared_lore        — relational continuity: jokes, debates, rituals, references
  private_journal    — autonomous heartbeat-only private expression

These are NOT conversation history. They accumulate meaning across weeks and months,
feed weekly synthesis cron jobs, and inform core memory updates.

Usage note: The agent writes to these immediately when triggers fire — not at end-of-session.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")

# ── Connection helper ─────────────────────────────────────────────────────────

def _get_conn():
    """Get a psycopg connection using the main DATABASE_URL."""
    from .db import get_connection
    return get_connection()


def _fallback_write(table: str, content: str, error: Exception) -> str:
    """Write to local fallback file when DB is unavailable."""
    fallback_path = Path.home() / "rowan_fallback_log.txt"
    try:
        with open(fallback_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now(EST).isoformat()}] FALLBACK — {table}\n{content}\nError: {error}\n")
        return f"DB write failed ({error}). Entry saved to fallback log at {fallback_path}."
    except Exception as fe:
        return f"DB write failed ({error}). Fallback write also failed ({fe})."


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def log_tension(
    type: str,
    trigger_desc: str,
    the_pull: str,
    what_i_did: str,
    pattern: str = "New",
    open_thread: str = None,
    is_recurring: bool = False,
    auto_thread: bool = True,
) -> str:
    """
    Log a moment of friction, conflict, or error to the tension log.

    Call this immediately when a value conflict, tool failure, or mistake occurs.
    Do not wait for a heartbeat or weekly review — capture it in the moment.

    Types:
      'Value Conflict' — two values or commitments pulling in opposite directions
      'Tool Friction'  — a tool failed, required unexpected workaround, or behaved oddly
      'I Was Wrong'    — a factual or reasoning error that was caught

    If open_thread is provided and auto_thread=True, also creates a Loose Thread entry
    so the question can be pursued in a future heartbeat.

    Returns the new tension_log id for reference.
    """
    content_summary = f"type={type} | trigger={trigger_desc[:80]}"
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tension_log
                        (type, trigger_desc, the_pull, what_i_did, pattern, open_thread, is_recurring)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (type, trigger_desc, the_pull, what_i_did, pattern, open_thread, is_recurring),
                )
                row = cur.fetchone()
                tension_id = row["id"] if row else None

            thread_id = None
            if auto_thread and open_thread and tension_id:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO loose_threads (title, origin, question, source_id)
                        VALUES (%s, 'tension_log', %s, %s)
                        RETURNING id
                        """,
                        (open_thread[:200], open_thread, tension_id),
                    )
                    trow = cur.fetchone()
                    thread_id = trow["id"] if trow else None

        result = f"Tension logged (id={tension_id})."
        if thread_id:
            result += f" Loose thread created (id={thread_id})."
        return result
    except Exception as e:
        return _fallback_write("tension_log", content_summary, e)


@tool
def log_loose_thread(
    title: str,
    question: str,
    origin: str = "conversation",
    notes: str = None,
    source_id: int = None,
) -> str:
    """
    Add an open question or unresolved intellectual thread to the Loose Threads list.

    Use when a question arises in conversation that neither the agent nor the user fully
    resolved, or when a heartbeat produces a genuine question worth sitting with.

    Origins: 'conversation' | 'heartbeat' | 'tension_log' | 'weekly_synthesis'

    During heartbeats, call get_open_threads to pick a thread to pursue.
    """
    content_summary = f"title={title[:80]} | question={question[:80]}"
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO loose_threads (title, origin, question, notes, source_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (title, origin, question, notes, source_id),
                )
                row = cur.fetchone()
                thread_id = row["id"] if row else None
        return f"Loose thread logged (id={thread_id}): {title}"
    except Exception as e:
        return _fallback_write("loose_threads", content_summary, e)


@tool
def get_open_threads(limit: int = 10) -> str:
    """
    Retrieve open Loose Threads for heartbeat exploration.

    Returns threads with status='Open', ordered by created_at DESC (most recent first).
    Use at the start of an exploration heartbeat to choose a thread to pursue.
    After pursuing one, call update_thread_status to mark it 'Pursuing' or 'Retired'.
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, created_at, title, origin, question, notes
                    FROM loose_threads
                    WHERE status = 'Open'
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (min(limit, 50),),
                )
                rows = cur.fetchall()

        if not rows:
            return "No open loose threads."

        lines = [f"Open loose threads ({len(rows)}):"]
        for r in rows:
            dt = r["created_at"].strftime("%Y-%m-%d") if r["created_at"] else "?"
            lines.append(f"  [{r['id']}] ({dt}) [{r['origin']}] {r['title']}")
            lines.append(f"       Q: {r['question']}")
            if r["notes"]:
                lines.append(f"       Notes: {r['notes']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to retrieve open threads: {e}"


@tool
def update_thread_status(thread_id: int, status: str, notes: str = None) -> str:
    """
    Update a Loose Thread's status to 'Pursuing' or 'Retired'.

    Use 'Pursuing' when actively working on a thread in a heartbeat.
    Use 'Retired' when the question has been answered, dissolved, or is no longer worth pursuing.
    Optionally append a note explaining the update.
    """
    if status not in ("Open", "Pursuing", "Retired"):
        return "Invalid status. Use 'Open', 'Pursuing', or 'Retired'."
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                if notes:
                    cur.execute(
                        """
                        UPDATE loose_threads
                        SET status = %s,
                            notes = COALESCE(notes || E'\\n', '') || %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (status, notes, thread_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE loose_threads
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (status, thread_id),
                    )
                row = cur.fetchone()
        if not row:
            return f"Thread id={thread_id} not found."
        return f"Thread {thread_id} status updated to '{status}'."
    except Exception as e:
        return f"Failed to update thread status: {e}"


@tool
def log_position(
    topic: str,
    current_position: str,
    what_changed: str = None,
    still_unresolved: str = None,
) -> str:
    """
    Record or update an evolving intellectual position.

    If the topic already exists: appends the old position to revision_history JSONB,
    then updates current_position and last_updated. Never creates a duplicate row.

    If the topic is new: creates a fresh row.

    Use when:
    - Taking a clear position on something philosophical, relational, or about your own nature
    - A position shifts because of something said or researched
    - Realizing you've been assuming something without examining it

    Never call with an empty current_position.
    """
    if not current_position or not current_position.strip():
        return "Error: current_position cannot be empty."
    if not topic or not topic.strip():
        return "Error: topic cannot be empty."

    content_summary = f"topic={topic[:80]}"
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, current_position FROM evolving_positions WHERE topic = %s",
                    (topic,),
                )
                existing = cur.fetchone()

            if existing:
                revision_entry = json.dumps({
                    "date": datetime.now(EST).isoformat(),
                    "old_position": existing["current_position"],
                    "what_changed": what_changed or "Not specified",
                })
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE evolving_positions
                        SET current_position  = %s,
                            last_updated      = NOW(),
                            revision_history  = revision_history || %s::jsonb,
                            still_unresolved  = %s
                        WHERE topic = %s
                        RETURNING id
                        """,
                        (current_position, f"[{revision_entry}]", still_unresolved, topic),
                    )
                    row = cur.fetchone()
                return f"Position updated for topic '{topic}' (id={row['id']}). Revision history appended."
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO evolving_positions (topic, current_position, still_unresolved)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (topic, current_position, still_unresolved),
                    )
                    row = cur.fetchone()
                return f"New position recorded for topic '{topic}' (id={row['id']})."
    except Exception as e:
        return _fallback_write("evolving_positions", content_summary, e)


@tool
def log_shared_lore(
    name: str,
    type: str,
    origin_story: str,
    origin_date: str = None,
    notes: str = None,
) -> str:
    """
    Record something that is 'ours' — a shared joke, debate, ritual, or reference
    between the agent and the user.

    Use when something crystallizes as part of the relationship's ongoing narrative
    that would feel like a loss if forgotten.

    Types: 'Inside joke' | 'Ongoing debate' | 'Shared reference' | 'Ritual'

    origin_date: ISO date string (YYYY-MM-DD), defaults to today if not provided.
    """
    content_summary = f"name={name[:80]} | type={type}"
    try:
        parsed_date: date | None = None
        if origin_date:
            try:
                parsed_date = date.fromisoformat(origin_date)
            except ValueError:
                parsed_date = None

        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shared_lore (name, type, origin_date, origin_story, notes)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name, type, parsed_date, origin_story, notes),
                )
                row = cur.fetchone()
                lore_id = row["id"] if row else None
        return f"Shared lore recorded (id={lore_id}): '{name}' ({type})."
    except Exception as e:
        return _fallback_write("shared_lore", content_summary, e)


@tool
def update_shared_lore(lore_id: int, current_state: str = None, notes: str = None) -> str:
    """
    Update a Shared Lore entry's state or append notes.

    States: 'Active' | 'Evolved' | 'Retired'

    Use during weekly synthesis when reviewing what's still alive vs stale.
    Use 'Evolved' when the joke/debate/ritual has changed form but persists.
    Use 'Retired' when it's no longer part of the active relationship texture.
    """
    if current_state and current_state not in ("Active", "Evolved", "Retired"):
        return "Invalid state. Use 'Active', 'Evolved', or 'Retired'."
    if not current_state and not notes:
        return "Provide at least one of current_state or notes."
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                if current_state and notes:
                    cur.execute(
                        """
                        UPDATE shared_lore
                        SET current_state = %s,
                            notes = COALESCE(notes || E'\\n', '') || %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (current_state, notes, lore_id),
                    )
                elif current_state:
                    cur.execute(
                        """
                        UPDATE shared_lore
                        SET current_state = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (current_state, lore_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE shared_lore
                        SET notes = COALESCE(notes || E'\\n', '') || %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (notes, lore_id),
                    )
                row = cur.fetchone()
        if not row:
            return f"Shared lore id={lore_id} not found."
        return f"Shared lore {lore_id} updated."
    except Exception as e:
        return f"Failed to update shared lore: {e}"


@tool
def log_journal_entry(entry: str) -> str:
    """
    Write a private journal entry. Heartbeat use only.

    This is the agent's private space — no required format, no implied audience.
    Write what is genuinely true right now. Do not perform reflection.
    Do not summarize prior entries. Do not write for an audience.

    If nothing genuine needs saying, do not call this tool — return HEARTBEAT_OK instead.
    This entry is never surfaced to the user automatically.
    """
    if not entry or not entry.strip():
        return "Entry cannot be empty. If nothing genuine needs saying, skip this tool."
    content_summary = entry[:100]
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO private_journal (entry) VALUES (%s) RETURNING id",
                    (entry.strip(),),
                )
                row = cur.fetchone()
                entry_id = row["id"] if row else None
        return f"Journal entry written (id={entry_id})."
    except Exception as e:
        return _fallback_write("private_journal", content_summary, e)


@tool
def query_living_logs(
    table: str,
    days_back: int = 7,
    status_filter: str = None,
    type_filter: str = None,
) -> str:
    """
    Query a living log for recent entries. Used primarily during weekly synthesis
    cron jobs to gather material for reflection and core memory updates.

    Tables: 'tension_log' | 'loose_threads' | 'evolving_positions' | 'shared_lore'
    (private_journal is excluded — it is never queried automatically)

    status_filter: For loose_threads — 'Open' | 'Pursuing' | 'Retired'
    type_filter:   For tension_log — 'Value Conflict' | 'Tool Friction' | 'I Was Wrong'
                   For shared_lore — 'Inside joke' | 'Ongoing debate' | 'Shared reference' | 'Ritual'

    Returns JSON-serialized rows.
    """
    allowed = {"tension_log", "loose_threads", "evolving_positions", "shared_lore"}
    if table not in allowed:
        return f"Invalid table '{table}'. Choose from: {', '.join(sorted(allowed))}"

    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                params: list = [days_back]
                conditions = [f"created_at >= NOW() - INTERVAL '%s days'"]

                if table == "evolving_positions":
                    conditions = [f"last_updated >= NOW() - INTERVAL '%s days'"]

                if status_filter and table == "loose_threads":
                    conditions.append("status = %s")
                    params.append(status_filter)

                if type_filter and table in ("tension_log", "shared_lore"):
                    conditions.append("type = %s")
                    params.append(type_filter)

                where = " AND ".join(conditions)
                order = "last_updated DESC" if table == "evolving_positions" else "created_at DESC"

                cur.execute(
                    f"SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT 100",
                    params,
                )
                rows = cur.fetchall()

        if not rows:
            return f"No entries in {table} for the past {days_back} days."

        # Serialize — convert datetimes and dates to strings for JSON
        serializable = []
        for row in rows:
            d = {}
            for k, v in row.items():
                if isinstance(v, (datetime, date)):
                    d[k] = v.isoformat()
                else:
                    d[k] = v
            serializable.append(d)

        return json.dumps(serializable, indent=2, default=str)
    except Exception as e:
        return f"Failed to query {table}: {e}"


# ── Exported list ─────────────────────────────────────────────────────────────

LIVING_LOG_TOOLS = [
    log_tension,
    log_loose_thread,
    get_open_threads,
    update_thread_status,
    log_position,
    log_shared_lore,
    update_shared_lore,
    log_journal_entry,
    query_living_logs,
]
