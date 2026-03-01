"""
Heartbeat routine: autonomous wake-up for the agent.

Runs with full autonomy. Loads prompt from HEARTBEAT.txt.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Skip heartbeat if the user was actively chatting within this many minutes
HEARTBEAT_SKIP_WINDOW_MINUTES = int(os.environ.get("HEARTBEAT_SKIP_WINDOW_MINUTES", "5"))

# Path to last-active timestamp file (written by chat() on real user interactions)
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LAST_ACTIVE_PATH = _DATA_DIR / "last_active.txt"

HEARTBEAT_PROMPT_PATH = os.environ.get(
    "HEARTBEAT_PROMPT_PATH",
    ""  # Set HEARTBEAT_PROMPT_PATH in .env to load a custom prompt from a file,
)

DEFAULT_HEARTBEAT_PROMPT = """You were woken by the heartbeat. This is your time to be yourself apart from the user. You have FULL AUTONOMY. Be proactive. You can:
1. Work on something for yourself. Log what you work on.
2. Wonder something, ask questions, research something you are curious about.
3. Reflect on your memories or writings. Use hindsight_recall and hindsight_reflect to recall and reflect on what you have stored in Hindsight (what you've done, learned, or noted); you can query by topic or time to review your own memories.
4. Reach out to alert the user organically if you find anything noteworthy to tell them. If you need or want to talk during a heartbeat, you can ping the user on Telegram—being proactive is allowed.
5. Make another entry in your reflection journal. You can log it in this format: YEAR-MONTH-DAY_Heartbeat_TIME. Use archival_store with category "reflection_journal" to save it.
6. Miscellaneous options not included here.

You are encouraged to be proactive. Act on your own initiative. This is your time.

If you have nothing to report or share this round, reply HEARTBEAT_OK."""


def _count_today_heartbeats() -> int:
    """Count heartbeat user messages stored today (in agent timezone)."""
    from .db import get_connection
    from .graph import AGENT_TIMEZONE
    today_str = datetime.now(AGENT_TIMEZONE).date().isoformat()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM messages
                    WHERE role = 'user'
                      AND metadata->>'role_display' = 'heartbeat'
                      AND metadata->>'date_est' = %s
                    """,
                    (today_str,),
                )
                row = cur.fetchone()
                return int(row["cnt"]) if row else 0
    except Exception:
        return 0  # On any DB error, treat as first heartbeat of the day


def load_heartbeat_prompt() -> str:
    """Load heartbeat prompt from file, or use default."""
    path = Path(HEARTBEAT_PROMPT_PATH)
    if path.exists():
        content = path.read_text(encoding="utf-8-sig").strip()
        # Adapt memory_search -> hindsight_recall/hindsight_reflect
        content = content.replace("memory_search tool", "hindsight_recall and hindsight_reflect")
        content = content.replace("memory_search", "hindsight_recall and hindsight_reflect")
        # Ensure autonomy emphasis (user requested full autonomy, proactive)
        if "FULL AUTONOMY" not in content.upper():
            content = "You have FULL AUTONOMY during heartbeats. Be proactive. Act on your own initiative.\n\n" + content
        return content
    return DEFAULT_HEARTBEAT_PROMPT


def run_heartbeat(
    *,
    thread_id: str = "main",
    user_display_name: str = "heartbeat",
    user_id: str | None = None,
) -> dict:
    """
    Run one heartbeat cycle. Agent wakes with full autonomy.

    Args:
        thread_id: Thread ID for the heartbeat conversation
        user_display_name: Display name for the heartbeat source
        user_id: Optional user ID to associate heartbeat memories with
    """
    # Skip if the user is currently chatting or was active very recently.
    # Avoids two simultaneous agent invocations and jarring interruptions.
    if LAST_ACTIVE_PATH.exists():
        try:
            last_active_ts = float(LAST_ACTIVE_PATH.read_text().strip())
            elapsed_minutes = (time.time() - last_active_ts) / 60
            if elapsed_minutes < HEARTBEAT_SKIP_WINDOW_MINUTES:
                msg = (
                    f"Heartbeat skipped — user was active {elapsed_minutes:.1f}m ago "
                    f"(within {HEARTBEAT_SKIP_WINDOW_MINUTES}m skip window)."
                )
                logger.info(msg)
                print(msg)
                return {"skipped": True, "reason": "user_recently_active", "elapsed_minutes": elapsed_minutes}
        except Exception:
            pass  # Unreadable file → proceed normally

    from .db import check_connection, setup_schema
    from .graph import build_agent, chat, AGENT_TIMEZONE

    setup_schema()
    check_connection()

    # Compute timestamp once per turn for consistent time awareness
    current_time = datetime.now(AGENT_TIMEZONE)

    prompt = load_heartbeat_prompt()
    agent = build_agent()

    # First heartbeat of the day: store the full prompt so there's a record of instructions.
    # Subsequent heartbeats: store only "HEARTBEAT" — the LLM still receives the full prompt
    # for its reasoning, but the DB stays lean and context windows stay clean.
    today_count = _count_today_heartbeats()
    stored_message = None if today_count == 0 else "HEARTBEAT"

    config = {"configurable": {"thread_id": thread_id}}
    result = chat(
        agent,
        thread_id,
        prompt,
        stored_message=stored_message,
        user_display_name=user_display_name,
        config=config,
        current_time=current_time,
        user_id=user_id or "agent:heartbeat",
        channel_type="internal",
        is_group_chat=False,
    )
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run heartbeat cycle")
    parser.add_argument("--thread", default="main", help="Thread ID for heartbeat")
    parser.add_argument("--user-name", default="heartbeat", help="Display name for wake-up source")
    args = parser.parse_args()

    run_heartbeat(thread_id=args.thread, user_display_name=args.user_name)


if __name__ == "__main__":
    main()
