"""
Backfill journal_entries from existing Railway Postgres messages.

Scans the `messages` table for:
  - Heartbeat assistant responses  (metadata->>'role_display' = 'heartbeat')
  - Cron job assistant responses   (metadata->>'role_display' = 'cron')
  - Daily summaries                (daily_summaries table, if it exists)

Inserts them into journal_entries in local Postgres (rowan-data).
Already-existing entries (same created_at timestamp) are skipped via
a dedup check, so this script is safe to run multiple times.

Usage:
    python scripts/backfill_journal.py
    python scripts/backfill_journal.py --dry-run   # preview without writing
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg
from psycopg.rows import dict_row

EST = ZoneInfo("America/New_York")


def get_railway_conn():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL not set in .env")
    return psycopg.connect(url, row_factory=dict_row)


def get_local_conn():
    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("KNOWLEDGE_DATABASE_URL not set in .env")
    return psycopg.connect(url, row_factory=dict_row)


def _detect_type(content: str, cron_name: str | None) -> tuple[str, str | None]:
    """Detect entry type and title from content/cron name."""
    name = (cron_name or "").lower()
    text = content.lower()[:500]

    if "wonder" in name or "1 am wonder" in name:
        return "wonder", cron_name or "1 AM Wonder"
    if "reflect" in name or "2 am reflect" in name:
        return "reflection", cron_name or "2 AM Reflection"
    if "research" in name:
        topic_match = re.match(
            r"^(.+?)\s*[-–]\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            name, re.I
        )
        title = topic_match.group(1).strip().title() if topic_match else (cron_name or "Research")
        return "research", title

    if any(w in text for w in ["wonder", "curious", "what if", "i wonder"]):
        return "wonder", "Wonder"
    if any(w in text for w in ["reflect", "reflection", "looking back", "i've been thinking"]):
        return "reflection", "Reflection"
    if any(w in text for w in ["research", "found that", "according to", "studied"]):
        return "research", "Research"

    return "heartbeat", cron_name or "Heartbeat"


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _extract_cron_name(user_content: str) -> str | None:
    """Extract cron job name from '[Cron: JobName]\n\n...' user message."""
    m = re.match(r"^\[Cron:\s*(.+?)\]", user_content or "")
    return m.group(1).strip() if m else None


def backfill(dry_run: bool = False) -> None:
    print(f"{'[DRY RUN] ' if dry_run else ''}Backfilling journal from Railway Postgres...\n")

    railway = get_railway_conn()
    local = get_local_conn()

    # Ensure journal schema exists
    if not dry_run:
        from src.agent.journal import ensure_schema
        ensure_schema()

    # Load existing journal created_at timestamps to avoid duplicates
    existing_ts: set[str] = set()
    with local.cursor() as cur:
        cur.execute("SELECT created_at FROM journal_entries")
        for row in cur.fetchall():
            existing_ts.add(row["created_at"].isoformat())

    print(f"  Existing journal entries: {len(existing_ts)}")

    inserted = 0
    skipped = 0

    # ── 1. Heartbeat assistant responses ──────────────────────────────────────
    print("\n  Scanning heartbeat messages...")
    with railway.cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.content, m.created_at, m.metadata
            FROM messages m
            WHERE m.role = 'assistant'
              AND m.metadata->>'role_display' = 'heartbeat'
            ORDER BY m.created_at ASC
            """
        )
        rows = cur.fetchall()

    print(f"    Found {len(rows)} heartbeat assistant messages")

    for row in rows:
        ts = row["created_at"].isoformat()
        if ts in existing_ts:
            skipped += 1
            continue
        content = (row["content"] or "").strip()
        if not content or content.upper() == "HEARTBEAT_OK":
            skipped += 1
            continue

        entry_type, title = _detect_type(content, None)
        edate = row["created_at"].astimezone(EST).date()

        if dry_run:
            print(f"    [DRY] {edate} {entry_type}: {title!r} ({_word_count(content)} words)")
        else:
            with local.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (entry_date, entry_type, title, content, word_count, source, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'heartbeat', '{}', %s, %s)
                    """,
                    (edate, entry_type, title, content, _word_count(content),
                     row["created_at"], row["created_at"]),
                )
        existing_ts.add(ts)
        inserted += 1

    # ── 2. Cron job assistant responses ───────────────────────────────────────
    # Strategy: find pairs of (user cron message, next assistant message) on same thread
    print("\n  Scanning cron job messages...")
    with railway.cursor() as cur:
        cur.execute(
            """
            SELECT id, idx, content, created_at, metadata
            FROM messages
            WHERE thread_id = 'main'
              AND metadata->>'role_display' = 'cron'
            ORDER BY created_at ASC
            """
        )
        cron_user_rows = cur.fetchall()

    print(f"    Found {len(cron_user_rows)} cron user messages")

    for user_row in cron_user_rows:
        cron_name = _extract_cron_name(user_row["content"])
        user_idx = user_row["idx"]

        # Get the immediately following assistant message
        with railway.cursor() as cur:
            cur.execute(
                """
                SELECT content, created_at
                FROM messages
                WHERE thread_id = 'main'
                  AND role = 'assistant'
                  AND idx > %s
                ORDER BY idx ASC
                LIMIT 1
                """,
                (user_idx,),
            )
            asst = cur.fetchone()

        if not asst:
            continue

        ts = asst["created_at"].isoformat()
        if ts in existing_ts:
            skipped += 1
            continue

        content = (asst["content"] or "").strip()
        if not content or content.upper() == "HEARTBEAT_OK":
            skipped += 1
            continue

        entry_type, title = _detect_type(content, cron_name)
        edate = asst["created_at"].astimezone(EST).date()

        if dry_run:
            print(f"    [DRY] {edate} {entry_type}: {title!r} ({_word_count(content)} words) [cron: {cron_name}]")
        else:
            with local.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (entry_date, entry_type, title, content, word_count, source, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'heartbeat', %s, %s, %s)
                    """,
                    (
                        edate, entry_type, title, content, _word_count(content),
                        psycopg.types.json.Jsonb({"cron_name": cron_name}),
                        asst["created_at"], asst["created_at"],
                    ),
                )
        existing_ts.add(ts)
        inserted += 1

    # ── 3. Daily summaries ────────────────────────────────────────────────────
    print("\n  Scanning daily summaries...")
    try:
        with railway.cursor() as cur:
            cur.execute(
                "SELECT summary_date, content, created_at FROM daily_summaries ORDER BY summary_date ASC"
            )
            summary_rows = cur.fetchall()
        print(f"    Found {len(summary_rows)} daily summaries")

        for row in summary_rows:
            ts = row["created_at"].isoformat()
            content = (row["content"] or "").strip()
            if not content:
                continue

            # Check if a summary already exists for this date
            with local.cursor() as cur:
                cur.execute(
                    "SELECT id FROM journal_entries WHERE entry_date = %s AND entry_type = 'summary'",
                    (row["summary_date"],),
                )
                existing_summary = cur.fetchone()

            if existing_summary:
                skipped += 1
                continue

            edate = row["summary_date"]
            created = row["created_at"] if row["created_at"] else datetime.now(EST)

            if dry_run:
                print(f"    [DRY] {edate} summary ({_word_count(content)} words)")
            else:
                with local.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO journal_entries
                            (entry_date, entry_type, title, content, word_count, source, created_at, updated_at)
                        VALUES (%s, 'summary', 'Daily Summary', %s, %s, 'daily_summary', %s, %s)
                        """,
                        (edate, content, _word_count(content), created, created),
                    )
            inserted += 1

    except psycopg.errors.UndefinedTable:
        print("    (No daily_summaries table found — skipping)")

    # ── Commit ────────────────────────────────────────────────────────────────
    if not dry_run:
        local.commit()

    railway.close()
    local.close()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped (already exists or empty): {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill journal from Railway Postgres")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
