#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill daily_summaries table from journal_entries or cron/conversation message history.

Run when a summary was produced but didn't make it into the daily_summaries context table
(e.g. scheduler was down when the cron fired, or the agent wrote the summary as text
without calling the daily_summary_write tool).

Usage:
    python scripts/backfill_daily_summaries.py              # dry-run: show what would be inserted
    python scripts/backfill_daily_summaries.py --apply      # actually insert missing summaries
    python scripts/backfill_daily_summaries.py --days 14    # search further back (default 8)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Force UTF-8 output on Windows so emoji in summary content doesn't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

import os
EST = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers to query Railway Postgres (daily_summaries + messages tables)
# ---------------------------------------------------------------------------

def _get_railway_conn():
    from src.agent.db import get_connection
    return get_connection()


def get_existing_summary_dates() -> dict[str, str]:
    """Return {date_str: content} for all summaries in daily_summaries."""
    with _get_railway_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT summary_date::text AS d, content FROM daily_summaries ORDER BY summary_date DESC"
            )
            rows = cur.fetchall()
    return {r["d"]: r["content"] for r in rows}


def find_summaries_in_cron_messages(cutoff: datetime) -> list[dict]:
    """
    Search the messages table for cron assistant messages that look like daily summaries.
    These are stored by cron_scheduler but never forwarded to daily_summaries.
    """
    with _get_railway_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    metadata->>'date_est' AS date_est,
                    created_at,
                    content
                FROM messages
                WHERE thread_id = 'main'
                  AND role = 'assistant'
                  AND metadata->>'role_display' = 'cron'
                  AND created_at >= %s
                  AND (
                      content ILIKE '%%daily summary%%'
                      OR content ILIKE '%%summary of today%%'
                      OR content ILIKE '%%today was%%'
                      OR content ILIKE '%%today i%%'
                      OR content ILIKE '%%summary for%%'
                      OR content ILIKE '%%this has been a%%'
                      OR content ILIKE '%%key moments%%'
                      OR content ILIKE '%%highlights of%%'
                  )
                ORDER BY created_at DESC
                """,
                (cutoff,),
            )
            rows = cur.fetchall()

    results = []
    for r in rows:
        # Use date_est metadata if available, else fall back to created_at date
        date = r["date_est"] or r["created_at"].astimezone(EST).strftime("%Y-%m-%d")
        results.append({
            "date": date,
            "content": r["content"],
            "source": "messages(cron assistant)",
            "created_at": r["created_at"].isoformat(),
        })
    return results


def find_summaries_in_conversation(cutoff: datetime) -> list[dict]:
    """
    Broaden the search: look at ALL assistant messages (not just cron-tagged)
    in case the agent wrote a daily summary in a regular conversation.
    Only pick up messages that explicitly mention writing/saving a daily summary.
    """
    with _get_railway_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    metadata->>'date_est' AS date_est,
                    created_at,
                    content
                FROM messages
                WHERE thread_id = 'main'
                  AND role = 'assistant'
                  AND created_at >= %s
                  AND (
                      content ILIKE '%%daily summary saved%%'
                      OR content ILIKE '%%i''ve saved a daily summary%%'
                      OR content ILIKE '%%i''ve written a daily summary%%'
                      OR content ILIKE '%%saved the daily summary%%'
                      OR content ILIKE '%%written the daily summary%%'
                  )
                ORDER BY created_at DESC
                """,
                (cutoff,),
            )
            rows = cur.fetchall()

    results = []
    for r in rows:
        date = r["date_est"] or r["created_at"].astimezone(EST).strftime("%Y-%m-%d")
        results.append({
            "date": date,
            "content": r["content"],
            "source": "messages(conversation - summary mention)",
            "created_at": r["created_at"].isoformat(),
        })
    return results


# ---------------------------------------------------------------------------
# Helpers to query local Postgres (journal_entries — KNOWLEDGE_DATABASE_URL)
# ---------------------------------------------------------------------------

def find_summaries_in_journal(cutoff: datetime) -> list[dict]:
    """
    Search journal_entries (local Postgres) for entry_type='summary' entries
    that were stored by save_heartbeat_output but not forwarded to daily_summaries.
    """
    kb_url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not kb_url:
        print("  [journal] KNOWLEDGE_DATABASE_URL not set — skipping journal search.")
        return []
    try:
        import psycopg
        conn = psycopg.connect(kb_url, row_factory=psycopg.rows.dict_row)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entry_date::text AS date, content, created_at
                    FROM journal_entries
                    WHERE entry_type = 'summary'
                      AND created_at >= %s
                    ORDER BY entry_date DESC, created_at DESC
                    """,
                    (cutoff,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {
                "date": r["date"],
                "content": r["content"],
                "source": "journal_entries(entry_type=summary)",
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"  [journal] Query failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Main backfill logic
# ---------------------------------------------------------------------------

def backfill(days: int = 8, apply: bool = False) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n=== Daily Summary Backfill ({mode}, last {days} days) ===\n")

    # What's already in daily_summaries?
    existing = get_existing_summary_dates()
    if existing:
        print("Existing daily_summaries (most recent first):")
        for d in sorted(existing.keys(), reverse=True):
            print(f"  {d} — {existing[d][:80]}...")
    else:
        print("  daily_summaries table is empty.")
    print()

    cutoff = datetime.now(EST) - timedelta(days=days)

    print("Searching for missing summaries...\n")

    # Gather candidates from all three sources (priority: journal > cron messages > conversation)
    journal_hits     = find_summaries_in_journal(cutoff)
    cron_hits        = find_summaries_in_cron_messages(cutoff)
    conversation_hits = find_summaries_in_conversation(cutoff)

    # Build merged dict per date: highest-priority source wins
    candidates: dict[str, dict] = {}
    for hit in conversation_hits:
        candidates[hit["date"]] = hit
    for hit in cron_hits:
        candidates[hit["date"]] = hit       # cron takes priority over conversation
    for hit in journal_hits:
        candidates[hit["date"]] = hit       # journal takes priority over cron messages

    if not candidates:
        print("No summary candidates found in any source.")
        print(
            "The summary may not have been produced (scheduler was likely down during the\n"
            "scheduled job time). You can ask the agent to write a summary now for any date."
        )
        return

    print(f"Found {len(candidates)} candidate date(s):\n")

    inserted = 0
    skipped = 0
    for date in sorted(candidates.keys(), reverse=True):
        hit = candidates[date]
        if date in existing:
            print(f"  {date} — already in daily_summaries (skipping)")
            print(f"           source: {hit['source']}")
            skipped += 1
            continue

        print(f"  {date} — MISSING from daily_summaries")
        print(f"           source:  {hit['source']}")
        print(f"           created: {hit.get('created_at', 'unknown')}")
        preview = hit['content'][:200].strip().encode('ascii', 'replace').decode('ascii')
        print(f"           preview: {preview}...")
        print()

        if apply:
            from src.agent.db import upsert_daily_summary
            upsert_daily_summary(date, hit["content"])
            print(f"           [INSERTED] into daily_summaries for {date}\n")
            inserted += 1
        else:
            print(f"           [dry-run] Would insert -- re-run with --apply to commit\n")

    print("-" * 60)
    if apply:
        print(f"Done: {inserted} summary/summaries inserted, {skipped} already present.")
    else:
        print(
            f"Dry-run complete: {len(candidates) - skipped} would be inserted, "
            f"{skipped} already present.\n"
            f"Re-run with --apply to commit changes."
        )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Backfill daily_summaries from journal or message history."
    )
    p.add_argument("--days", type=int, default=8, help="Days back to search (default: 8)")
    p.add_argument("--apply", action="store_true", help="Actually insert (default: dry-run)")
    args = p.parse_args()
    backfill(days=args.days, apply=args.apply)
