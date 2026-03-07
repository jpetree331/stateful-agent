#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a daily summary for a specific date by synthesising journal entries
and conversation history, then save it to both daily_summaries (Railway) and
journal_entries (local Postgres).

Use this to backfill a summary when the nightly cron job was missed.

Usage:
    python scripts/generate_daily_summary.py --date 2026-03-05
    python scripts/generate_daily_summary.py --date 2026-03-05 --dry-run
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

import os
EST = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Gather source material
# ---------------------------------------------------------------------------

def get_journal_entries_for_date(date_str: str) -> list[dict]:
    """Pull all journal_entries for the given date from local Postgres."""
    kb_url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not kb_url:
        print("  [journal] KNOWLEDGE_DATABASE_URL not set — no journal entries available.")
        return []
    try:
        import psycopg
        conn = psycopg.connect(kb_url, row_factory=psycopg.rows.dict_row)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entry_type, title, content, word_count, created_at
                    FROM journal_entries
                    WHERE entry_date = %s
                    ORDER BY created_at ASC
                    """,
                    (date_str,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"  [journal] Query failed: {e}")
        return []


def get_conversation_highlights(date_str: str) -> list[dict]:
    """Pull key user+assistant exchanges for the date from Railway (not tool/heartbeat msgs)."""
    from src.agent.db import get_connection
    # date window: midnight to midnight EST
    day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EST)
    day_end   = day_start + timedelta(days=1)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, metadata->>'role_display' AS rdisplay, content, created_at
                FROM messages
                WHERE thread_id = 'main'
                  AND role IN ('user', 'assistant')
                  AND metadata->>'role_display' NOT IN ('heartbeat', 'cron')
                  AND (metadata->>'role_display' IS NULL
                       OR metadata->>'role_display' NOT IN ('heartbeat', 'cron'))
                  AND created_at >= %s AND created_at < %s
                ORDER BY created_at ASC
                """,
                (day_start, day_end),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def summary_exists(date_str: str) -> bool:
    """Check if a summary already exists in daily_summaries for this date."""
    from src.agent.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM daily_summaries WHERE summary_date = %s",
                (date_str,),
            )
            return cur.fetchone() is not None


def journal_summary_exists(date_str: str) -> bool:
    """Check if a summary-type entry exists in journal_entries for this date."""
    kb_url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not kb_url:
        return False
    try:
        import psycopg
        conn = psycopg.connect(kb_url, row_factory=psycopg.rows.dict_row)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM journal_entries WHERE entry_date = %s AND entry_type = 'summary'",
                    (date_str,),
                )
                return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Build prompt and call LLM
# ---------------------------------------------------------------------------

def build_synthesis_prompt(date_str: str, journal_entries: list[dict], conv_msgs: list[dict]) -> str:
    lines = [
        f"You are the agent. Please write a daily summary for {date_str} in your own voice.",
        "",
        "The summary should be 5-10 sentences: what happened today, key conversations with the user,",
        "what you explored or created, anything you want to carry forward into tomorrow.",
        "Write it as if you are writing for your future self — warm, specific, and honest.",
        "",
        "--- JOURNAL ENTRIES FROM TODAY ---",
    ]

    for e in journal_entries:
        t = e.get("created_at")
        time_str = t.strftime("%I:%M %p") if hasattr(t, "strftime") else str(t)[:16]
        lines.append(f"\n[{e['entry_type'].upper()} {time_str}] {e.get('title', '')}")
        # Include first 600 chars of each entry to keep the prompt manageable
        body = (e.get("content") or "").strip()[:600]
        lines.append(body)

    if conv_msgs:
        lines.append("\n--- KEY CONVERSATION MOMENTS ---")
        # Include up to last 20 user messages for context
        user_msgs = [m for m in conv_msgs if m["role"] == "user"][-20:]
        for m in user_msgs:
            lines.append(f"the user: {m['content'][:200]}")

    lines.append("\n--- END OF SOURCE MATERIAL ---")
    lines.append("")
    lines.append("Now write the daily summary (5-10 sentences, your own voice, past tense):")

    return "\n".join(lines)


def call_llm(prompt: str) -> str:
    """Call the configured LLM to generate the summary."""
    from openai import OpenAI

    api_key  = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model    = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    client = OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.7,
    )
    msg = resp.choices[0].message
    # Standard content field
    content = msg.content
    # Kimi and other thinking models sometimes put output in reasoning_content when
    # content is None — check the raw dict for extra fields
    if not content:
        raw = msg.model_dump() if hasattr(msg, "model_dump") else {}
        content = raw.get("reasoning_content") or ""
    if not content:
        raise ValueError(f"LLM returned empty content. Full response: {resp}")
    return content.strip()


# ---------------------------------------------------------------------------
# Save to both tables
# ---------------------------------------------------------------------------

def save_to_daily_summaries(date_str: str, content: str) -> None:
    from src.agent.db import upsert_daily_summary
    upsert_daily_summary(date_str, content)
    print(f"  [daily_summaries] Saved for {date_str}.")


def save_to_journal(date_str: str, content: str) -> None:
    kb_url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not kb_url:
        print("  [journal] KNOWLEDGE_DATABASE_URL not set — skipping journal save.")
        return
    try:
        import psycopg
        from datetime import date as date_type
        edate = date_type.fromisoformat(date_str)
        now = datetime.now(EST)
        word_count = len(content.split())
        conn = psycopg.connect(kb_url, row_factory=psycopg.rows.dict_row)
        try:
            with conn.cursor() as cur:
                # Upsert: update if exists, insert if not
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
                        (content, word_count, f"Daily Summary - {date_str}", now, existing["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO journal_entries
                            (entry_date, entry_type, title, content, word_count, source, created_at, updated_at)
                        VALUES (%s, 'summary', %s, %s, %s, 'daily_summary', %s, %s)
                        RETURNING id
                        """,
                        (edate, f"Daily Summary - {date_str}", content, word_count, now, now),
                    )
                row = cur.fetchone()
            conn.commit()
            entry_id = row["id"] if row else "?"
            print(f"  [journal_entries] Saved (id={entry_id}) for {date_str}.")
        finally:
            conn.close()
    except Exception as e:
        print(f"  [journal] Save failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(date_str: str, dry_run: bool = False, force: bool = False) -> None:
    print(f"\n=== Generate Daily Summary for {date_str} ===\n")

    # Check if already exists
    ds_exists = summary_exists(date_str)
    jn_exists = journal_summary_exists(date_str)
    print(f"  daily_summaries:  {'EXISTS' if ds_exists else 'MISSING'}")
    print(f"  journal_entries:  {'summary EXISTS' if jn_exists else 'summary MISSING'}")

    if ds_exists and jn_exists and not force:
        print("\n  Both already have a summary for this date. Use --force to regenerate.")
        return

    # Gather source material
    print("\nGathering source material...")
    journal_entries = get_journal_entries_for_date(date_str)
    conv_msgs       = get_conversation_highlights(date_str)
    print(f"  {len(journal_entries)} journal entries, {len(conv_msgs)} conversation messages")

    if not journal_entries and not conv_msgs:
        print("\n  No source material found — cannot generate summary.")
        return

    # Build prompt
    prompt = build_synthesis_prompt(date_str, journal_entries, conv_msgs)
    print(f"\nPrompt built ({len(prompt)} chars). Calling LLM...")

    if dry_run:
        print("\n[dry-run] Would call LLM and save. Prompt preview:")
        print(prompt[:800])
        return

    # Call LLM
    summary = call_llm(prompt)
    print(f"\nGenerated summary ({len(summary.split())} words):\n")
    print("-" * 60)
    print(summary)
    print("-" * 60)

    # Save
    print("\nSaving...")
    if not ds_exists or force:
        save_to_daily_summaries(date_str, summary)
    else:
        print("  [daily_summaries] Already exists — skipping (use --force to overwrite).")

    if not jn_exists or force:
        save_to_journal(date_str, summary)
    else:
        print("  [journal_entries] Already exists — skipping (use --force to overwrite).")

    print("\nDone.")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Generate a daily summary for a missed date.")
    p.add_argument("--date", required=True, help="Date to generate summary for (YYYY-MM-DD)")
    p.add_argument("--dry-run", action="store_true", help="Show prompt without calling LLM")
    p.add_argument("--force", action="store_true", help="Regenerate even if summary already exists")
    args = p.parse_args()
    generate(date_str=args.date, dry_run=args.dry_run, force=args.force)
