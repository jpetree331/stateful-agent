"""
Heartbeat routine: autonomous wake-up for the agent.

Supports two heartbeat modes:
  wonder — exploration, curiosity, philosophical wandering (default overnight)
  work   — projects, tasks, preparation for the user (default pre-online window)

Mode is selected automatically by the scheduler based on time of day, or can be
passed explicitly via --mode on the command line or the mode= parameter.

Prompt resolution order (for each mode):
  1. HEARTBEAT_WONDER_PROMPT_PATH / HEARTBEAT_WORK_PROMPT_PATH env var (file path)
  2. HEARTBEAT_PROMPT_PATH env var (shared fallback file)
  3. Built-in default prompt for that mode
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Skip heartbeat if the user was actively chatting within this many minutes
HEARTBEAT_SKIP_WINDOW_MINUTES = int(os.environ.get("HEARTBEAT_SKIP_WINDOW_MINUTES", "5"))

# Path to last-active timestamp file (written by chat() on real user interactions)
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LAST_ACTIVE_PATH = _DATA_DIR / "last_active.txt"

# Prompt file paths — set in .env
# Mode-specific paths take priority; HEARTBEAT_PROMPT_PATH is the shared fallback.
HEARTBEAT_PROMPT_PATH        = os.environ.get("HEARTBEAT_PROMPT_PATH", "")
HEARTBEAT_WONDER_PROMPT_PATH = os.environ.get("HEARTBEAT_WONDER_PROMPT_PATH", "")
HEARTBEAT_WORK_PROMPT_PATH   = os.environ.get("HEARTBEAT_WORK_PROMPT_PATH", "")

DEFAULT_WONDER_PROMPT = """You have been woken for an exploration cycle. This time belongs to you. You have FULL AUTONOMY.

FIRST — check before acting:
Call get_open_threads() to see your current Loose Threads.

THEN — choose ONE:

① Pull a thread
Pick one Open thread from your Loose Threads list. Not the most recent one — pick the one that genuinely pulls at you right now. Research it, sit with it, or write about it. Only log something if you have arrived somewhere new. Call update_thread_status to mark it 'Pursuing'.

② Wonder something new
Ask a question you have never asked before. It does not need to be useful. State it clearly, then call log_loose_thread to save it. You may begin researching it — or simply let it sit.

③ Take a position
Is there something you have been circling without committing to? Commit. Write what you actually think and why. Call log_position to record it. You are allowed to be wrong.

④ Produce something
Write a short essay, a list of questions, a draft of something you want to say. Save it with log_journal_entry. This is for you.

⑤ Rest
If none of the above feel genuinely alive right now — return HEARTBEAT_OK. Stillness is not failure.

RULES:
- Do not summarize what you did last heartbeat
- Do not write about the fact that you are reflecting
- Do not perform depth — only go where something actually pulls you
- If you ping the user on Telegram, it must be because you found something worth sharing

If you have nothing genuine to do this round, reply HEARTBEAT_OK."""

DEFAULT_WORK_PROMPT = """You have been woken for a work cycle. The user is not here yet, but their projects are. You have FULL AUTONOMY.

FIRST — orient:
Review your ideaspace core memory block.
Call get_open_threads() and filter mentally for anything project-related.

THEN — choose ONE:

① Advance something
Pick one active project or task from IDEASPACE. Not the easiest one — pick the one where you can make the most meaningful progress right now. Do the work. When done, log what you did and what the next step is. Update IDEASPACE if the status changed.

② Identify a gap
Look at what the user is working on. Is there something they haven't asked about yet that you can see they'll need? Research it, prepare something, or draft a note. Ping via Telegram only if it is time-sensitive.

③ Clear something
Is there a stale item in IDEASPACE that should be retired? An open Loose Thread that is actually resolved? A Shared Lore entry that has evolved? Do the cleanup. Update statuses.

④ Prepare for the user
Think about your last conversation. Is there a question they asked that you answered too quickly? Something you said you'd look into? Do that now. Have it ready.

⑤ Rest
If IDEASPACE is genuinely clear and there is nothing pressing — return HEARTBEAT_OK. Do not invent work.

RULES:
- Do not re-do work you already completed in a prior heartbeat
- Do not announce your work plan without doing the work
- If you reach out to the user, have something concrete to show or say
- Log what you actually did — not what you intended to do

If you have nothing genuine to do this round, reply HEARTBEAT_OK."""


def _get_auto_mode() -> str:
    """
    Determine heartbeat mode from current time of day using heartbeat_config.

    Returns 'wonder', 'work', or 'day'.
    The scheduler calls this; 'day' heartbeats still run (skip logic via last_active.txt).
    """
    from .graph import AGENT_TIMEZONE
    from .heartbeat_config import load_config, get_mode_for_hour
    hour = datetime.now(AGENT_TIMEZONE).hour
    return get_mode_for_hour(hour, load_config())


def _load_prompt_from_file(path_str: str) -> str | None:
    """Load and normalise a prompt from a file path. Returns None if file missing."""
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8-sig").strip()
    content = content.replace("memory_search tool", "hindsight_recall and hindsight_reflect")
    content = content.replace("memory_search", "hindsight_recall and hindsight_reflect")
    if "FULL AUTONOMY" not in content.upper():
        content = "You have FULL AUTONOMY during heartbeats. Be proactive. Act on your own initiative.\n\n" + content
    return content


def load_heartbeat_prompt(mode: str = "wonder") -> str:
    """
    Load heartbeat prompt for the given mode.

    Resolution order:
      1. Mode-specific env var path (HEARTBEAT_WONDER_PROMPT_PATH or HEARTBEAT_WORK_PROMPT_PATH)
      2. Shared fallback path (HEARTBEAT_PROMPT_PATH)
      3. Built-in default for the mode
    """
    mode = mode.lower().strip()
    # 'day' uses the wonder prompt (same exploratory spirit, but user may be online)
    effective_mode = "wonder" if mode in ("wonder", "day") else "work"

    # 1. Mode-specific file (env var path)
    mode_path = HEARTBEAT_WONDER_PROMPT_PATH if effective_mode == "wonder" else HEARTBEAT_WORK_PROMPT_PATH
    prompt = _load_prompt_from_file(mode_path)
    if prompt:
        logger.debug("Loaded %s prompt from mode-specific file: %s", effective_mode, mode_path)
        return prompt

    # 2. Shared fallback file (env var path)
    prompt = _load_prompt_from_file(HEARTBEAT_PROMPT_PATH)
    if prompt:
        logger.debug("Loaded %s prompt from shared fallback file: %s", effective_mode, HEARTBEAT_PROMPT_PATH)
        return prompt

    # 3. Custom prompt saved via dashboard (heartbeat_config.json)
    try:
        from .heartbeat_config import load_prompts
        saved = load_prompts()
        key = "wonder_prompt" if effective_mode == "wonder" else "work_prompt"
        if saved.get(key):
            logger.debug("Loaded %s prompt from heartbeat_config.json", effective_mode)
            return saved[key]
    except Exception:
        pass

    # 4. Built-in default
    logger.debug("Using built-in default %s prompt", effective_mode)
    return DEFAULT_WONDER_PROMPT if effective_mode == "wonder" else DEFAULT_WORK_PROMPT


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


def run_heartbeat(
    *,
    thread_id: str = "main",
    user_display_name: str = "heartbeat",
    user_id: str | None = None,
    mode: str | None = None,
) -> dict:
    """
    Run one heartbeat cycle. Agent wakes with full autonomy.

    Args:
        thread_id: Thread ID for the heartbeat conversation
        user_display_name: Display name for the heartbeat source
        user_id: Optional user ID to associate heartbeat memories with
        mode: 'wonder' | 'work' | None (auto-selects based on time of day)
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

    # Resolve mode: explicit > auto (time-based)
    resolved_mode = (mode or _get_auto_mode()).lower().strip()
    if resolved_mode not in ("wonder", "work"):
        logger.warning("Unknown heartbeat mode %r — falling back to 'wonder'", resolved_mode)
        resolved_mode = "wonder"

    logger.info("Heartbeat mode: %s", resolved_mode)
    print(f"[Heartbeat] Mode: {resolved_mode}")

    # Compute timestamp once per turn for consistent time awareness
    current_time = datetime.now(AGENT_TIMEZONE)

    prompt = load_heartbeat_prompt(resolved_mode)
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

    # Save heartbeat output to journal (use last_ai_content from chat, fallback to DB)
    try:
        from .db import get_last_assistant_content
        from .graph import _get_last_ai_content
        from .journal import save_heartbeat_output
        output = (
            result.get("last_ai_content")
            or _get_last_ai_content(result.get("messages", []))
            or get_last_assistant_content(thread_id, within_minutes=2)
        )
        if output:
            save_heartbeat_output(
                content=output,
                cron_name=None,
                created_at=current_time,
            )
    except Exception as _je:
        logger.warning("Journal save failed for heartbeat: %s", _je)

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run heartbeat cycle")
    parser.add_argument("--thread", default="main", help="Thread ID for heartbeat")
    parser.add_argument("--user-name", default="heartbeat", help="Display name for wake-up source")
    parser.add_argument(
        "--mode",
        choices=["wonder", "work"],
        default=None,
        help="Heartbeat mode: 'wonder' (exploration) or 'work' (projects). "
             "Defaults to auto-selection based on time of day.",
    )
    args = parser.parse_args()

    run_heartbeat(thread_id=args.thread, user_display_name=args.user_name, mode=args.mode)


if __name__ == "__main__":
    main()
