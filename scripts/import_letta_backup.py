#!/usr/bin/env python3
"""
Import Letta conversation backup into LangGraph Postgres (DB 1).

Reads the JSON file READ-ONLY. Original backup is never modified.
Imports: user_message, assistant_message, reasoning_message, tool_return_message.
Strips <system-reminder> blocks from user messages.
Use --overwrite to clear existing thread data before re-importing.
"""
from __future__ import annotations

import json
import re
import sys
from psycopg.types.json import Jsonb
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.agent.db import get_connection, setup_schema

# Regex to strip Letta system reminders from user messages
SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>\s*",
    re.DOTALL | re.IGNORECASE,
)


def strip_system_reminders(content: str) -> str:
    """Remove Letta system-reminder blocks from user message content."""
    if not content:
        return content
    return SYSTEM_REMINDER_RE.sub("", content).strip()


def parse_date(s: str | None) -> datetime | None:
    """Parse ISO date from backup."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def import_backup(
    backup_path: str | Path,
    thread_id: str = "main",
    overwrite: bool = False,
) -> tuple[int, int, int]:
    """
    Import Letta backup into Postgres. Does NOT modify the backup file.

    Returns (user_count, assistant_count, tool_count) of imported messages.
    """
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    if not messages:
        print("No messages in backup.")
        return 0, 0, 0

    # Filter: user, assistant, reasoning, tool_return (incl. Hindsight)
    IMPORT_TYPES = {"user_message", "assistant_message", "reasoning_message", "tool_return_message"}
    filtered = []
    for m in messages:
        mt = m.get("message_type")
        if mt not in IMPORT_TYPES:
            continue
        if mt == "tool_return_message":
            if m.get("tool_return") is not None:
                filtered.append(m)
        elif m.get("content") is not None:
            filtered.append(m)

    # Sort by date for consistent ordering
    filtered.sort(key=lambda m: (parse_date(m.get("date")) or datetime.min, m.get("id", "")))

    # Build (role, content, metadata, reasoning) tuples
    to_insert: list[tuple[str, str, dict | None, str | None]] = []
    pending_reasoning: str | None = None
    user_count = 0
    assistant_count = 0
    tool_count = 0

    for m in filtered:
        msg_type = m.get("message_type")
        content = (m.get("content") or "").strip()
        tool_return = m.get("tool_return")
        date_val = m.get("date")

        if msg_type == "user_message":
            content = strip_system_reminders(content)
            if content:
                meta = {"source": "letta_import", "original_date": date_val}
                to_insert.append(("user", content, meta, None))
                user_count += 1

        elif msg_type == "reasoning_message":
            if content:
                pending_reasoning = content
            else:
                pending_reasoning = None

        elif msg_type == "assistant_message":
            meta = {"source": "letta_import", "original_date": date_val}
            reasoning = pending_reasoning
            pending_reasoning = None
            if content or reasoning:
                to_insert.append(("assistant", content or "(no content)", meta, reasoning))
                assistant_count += 1

        elif msg_type == "tool_return_message":
            if tool_return is not None:
                tool_content = tool_return if isinstance(tool_return, str) else str(tool_return)
                meta = {"source": "letta_import", "original_date": date_val, "type": "tool_return"}
                to_insert.append(("tool", tool_content, meta, None))
                tool_count += 1

    if not to_insert:
        print("No importable messages found.")
        return 0, 0, 0

    setup_schema()

    with get_connection() as conn:
        with conn.cursor() as cur:
            if overwrite:
                cur.execute("DELETE FROM messages WHERE thread_id = %s", (thread_id,))
                next_idx = 0
                print(f"Cleared existing messages for thread '{thread_id}'.")
            else:
                cur.execute(
                    "SELECT COALESCE(MAX(idx), -1) + 1 AS next_idx FROM messages WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
                next_idx = row["next_idx"] if row else 0

                if next_idx > 0:
                    print(f"WARNING: Thread '{thread_id}' already has {next_idx} messages.")
                    print("Use --overwrite to clear and re-import.")
                    resp = input("Continue (append)? [y/N]: ")
                    if resp.lower() != "y":
                        print("Aborted.")
                        return 0, 0, 0

            for role, content, meta_extra, reasoning in to_insert:
                metadata = dict(meta_extra or {})
                cur.execute(
                    """
                    INSERT INTO messages (thread_id, idx, role, content, reasoning, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (thread_id, next_idx, role, content, reasoning, Jsonb(metadata)),
                )
                next_idx += 1

    print(f"Imported {user_count} user + {assistant_count} assistant + {tool_count} tool messages to thread '{thread_id}'.")
    return user_count, assistant_count, tool_count


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import Letta backup into LangGraph DB")
    parser.add_argument(
        "backup",
        help="Path to backup .json file (read-only, never modified)",
    )
    parser.add_argument("--thread", default="main", help="Thread ID (default: main)")
    parser.add_argument("--overwrite", action="store_true", help="Clear existing thread data before importing")
    args = parser.parse_args()

    try:
        import_backup(args.backup, thread_id=args.thread, overwrite=args.overwrite)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
