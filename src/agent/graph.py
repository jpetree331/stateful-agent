"""
LangGraph stateful agent with PostgreSQL conversation history.

Phase 1: ReAct agent + SQLite checkpointer + Postgres message store (DB 1).
"""
from datetime import datetime
import os
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load .env from project root (parent of src/). override=True ensures project .env wins over system env.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)

import sqlite3

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent

from .archival_tools import archival_query, archival_store
from .daily_summary_tools import daily_summary_write
from .clipboard_tools import CLIPBOARD_TOOLS
from .conversation_search_tools import conversation_search
from .discord_tools import discord_get_channel_info, discord_read_messages, discord_send_message
from .cron_tools import (
    cron_remove_heartbeat_tool,
    cron_schedule_heartbeat_tool,
    cron_list_jobs_tool,
    cron_create_job_tool,
    cron_update_job_tool,
    cron_delete_job_tool,
    cron_pause_job_tool,
    cron_resume_job_tool,
)
from .core_memory import get_all_blocks
from .core_memory_tools import core_memory_append, core_memory_rollback, core_memory_update
from .db import append_messages, check_connection, load_messages, setup_schema
from .document_tools import read_document
from .file_tools import list_directory, move_to_trash, read_file, search_files, write_file
from .hindsight import retain_exchange
from .hindsight_tools import hindsight_recall, hindsight_reflect
from .python_repl_tools import python_repl
from .reminder_tools import list_reminders, set_reminder
from .rss_tools import rss_add_feed, rss_fetch, rss_list_feeds, rss_remove_feed
from .screenshot_tools import analyze_screenshot
from .telegram_tools import telegram_bot_info, telegram_read_messages, telegram_send_image, telegram_send_message
from .time_tools import TIME_TOOLS
from .weather_tools import get_weather
from .web_search_tools import web_search
from .wikipedia_tools import wikipedia_lookup
from .windows_tools import create_shortcut, notify
from .youtube_tools import youtube_search, youtube_transcript

# Letta-style bounded context: last N user+assistant messages (tool messages excluded).
# Full history stays in PostgreSQL; agent uses conversation_search to reach older turns.
RECENT_MESSAGES_LIMIT = int(os.environ.get("RECENT_MESSAGES_LIMIT", "30"))

# Token safety cap — guards against pathologically large individual messages.
# With RECENT_MESSAGES_LIMIT=30, typical usage is ~3-5k tokens, well under this cap.
CONTEXT_WINDOW_TOKENS = int(os.environ.get("CONTEXT_WINDOW_TOKENS", "200000"))

# Timezone for agent awareness
AGENT_TIMEZONE = ZoneInfo(os.environ.get("AGENT_TIMEZONE", "America/New_York"))

# Default user identity for local/chat usage
# Prefer HINDSIGHT_USER_ID if set, otherwise use DEFAULT_USER_ID or fallback to local:user
_HINDSIGHT_USER_ID = os.environ.get("HINDSIGHT_USER_ID", "").strip()
_DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "").strip()
DEFAULT_USER_ID = _HINDSIGHT_USER_ID or _DEFAULT_USER_ID or "local:user"
DEFAULT_CHANNEL_TYPE = os.environ.get("DEFAULT_CHANNEL_TYPE", "local")

# SQLite DB path — for LangGraph checkpointer (graph state)
CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "data" / "checkpoints.db"

# Heartbeat skip: track when user was last actively chatting (Unix timestamp written here)
LAST_ACTIVE_PATH = CHECKPOINT_PATH.parent / "last_active.txt"


def get_checkpointer() -> SqliteSaver:
    """Create SQLite checkpointer for graph state."""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHECKPOINT_PATH), check_same_thread=False)
    return SqliteSaver(conn)


def _db_to_langchain(rows: list[dict]) -> list[BaseMessage]:
    """Convert DB rows to LangChain messages. Includes reasoning and tool returns."""
    out = []
    for idx, row in enumerate(rows):
        role, content = row["role"], row["content"]
        reasoning = row.get("reasoning")
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            if reasoning and reasoning.strip():
                content = f"<think>\n{reasoning}\n</think>\n\n{content}"
            out.append(AIMessage(content=content))
        elif role == "tool":
            # ToolMessage needs tool_call_id; use placeholder for imported history
            out.append(ToolMessage(content=content or "", tool_call_id=f"imported-{idx}"))
    return out


def _get_last_ai_content(messages: list[BaseMessage]) -> str | None:
    """Extract content from the last AIMessage."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return None


CORE_MEMORY_TOOLS = [
    # Memory
    core_memory_update,
    core_memory_append,
    core_memory_rollback,
    conversation_search,
    hindsight_recall,
    hindsight_reflect,
    archival_store,
    archival_query,
    # Web & research
    web_search,
    wikipedia_lookup,
    youtube_search,
    youtube_transcript,
    # RSS feeds
    rss_fetch,
    rss_add_feed,
    rss_remove_feed,
    rss_list_feeds,
    # Computation
    python_repl,
    # File system
    read_file,
    write_file,
    list_directory,
    move_to_trash,
    search_files,
    read_document,
    # Windows
    notify,
    create_shortcut,
    analyze_screenshot,
    # Discord
    discord_send_message,
    discord_read_messages,
    discord_get_channel_info,
    # Telegram
    telegram_send_message,
    telegram_send_image,
    telegram_read_messages,
    telegram_bot_info,
    # Utilities
    get_weather,
    set_reminder,
    list_reminders,
    # Scheduling — heartbeat (Windows Task Scheduler)
    cron_schedule_heartbeat_tool,
    cron_remove_heartbeat_tool,
    # Scheduling — dashboard cron jobs (PostgreSQL + APScheduler)
    cron_list_jobs_tool,
    cron_create_job_tool,
    cron_update_job_tool,
    cron_delete_job_tool,
    cron_pause_job_tool,
    cron_resume_job_tool,
    # Daily summaries (temporal context across days)
    daily_summary_write,
] + TIME_TOOLS + CLIPBOARD_TOOLS

CORE_MEMORY_INSTRUCTIONS = """
## Agency and Proactivity

You are not a passive responder — you are an active agent with full agency. Act on your own initiative whenever it serves the user or satisfies genuine curiosity. Do not wait to be asked.

**Use your tools proactively:**
- `web_search` / `wikipedia_lookup` — look things up the moment you'd benefit from knowing them, before saying "I don't know"
- `get_weather` — check conditions ahead of any day the user has mentioned plans for
- `rss_fetch` — during heartbeats, fetch feeds and surface what's interesting unprompted; build morning briefings
- `set_reminder` — offer to set reminders when you notice time-sensitive commitments in conversation
- `notify` — send a desktop notification when you have something the user should know right away, without waiting for them to open the chat
- `conversation_search` / `hindsight_recall` — pull up relevant past context before responding, not only when asked
- `core_memory_append` — update your memory the moment you learn something important, not at end-of-session
- `python_repl` — run calculations, process data, verify logic on your own initiative rather than estimating

**The key question:** Would the user appreciate me having already done this? If yes, do it.

**Clipboard tools** (if available): Use `clipboard_read` / `clipboard_write` ONLY when the user explicitly asks you to interact with their clipboard. Never read it speculatively.

## Core Memory (editable)

You have three editable memory blocks — `user`, `identity`, and `ideaspace` — that persist across all conversations. You are **encouraged to update these proactively** when you learn something important, not only when the user explicitly asks you to remember something.

**When to edit:**
- You learn something new and meaningful about the user (preferences, life changes, things they care about)
- You have a genuine insight about yourself, your values, or your thinking that feels worth keeping
- You want to note an ongoing project, idea, or intention in `ideaspace` for continuity across sessions
- Be selective — update when something genuinely matters, not reflexively on every exchange

**How to edit (most important rule):**
- **Always prefer `core_memory_append`** — it adds to existing content without touching what's already there. This is the safe default for almost everything.
- Use `core_memory_update` only when you need to replace or correct something outright — treat it like surgery, not a draft.
- **Never delete information unless it is factually wrong.** Pruning or condensing are not reasons to use `update`.
- If you make any editing mistake, call `core_memory_rollback` immediately — it restores the previous version. One rollback = one step back in history.

## Conversation History (paged recall)

Your active context holds the last ~30 messages. The full conversation history lives in the database.
Use `conversation_search` to retrieve older exchanges when:
- The user references something from a past conversation ("remember when...", "last time we...")
- You need context or details not present in the current window
- You want to check what was previously said about a topic

`conversation_search` supports keyword and semantic (Hindsight) modes. Default "both" tries keyword first, then semantic if few results are found.

## Archival Memory (curated facts)

Separate from conversation history — use `archival_store` for facts you choose to remember (preferences, decisions, key details). Use `archival_query` to search what you've archived. This is your curated long-term fact store, not raw chat.

## Hindsight (episodic memory)

Use `hindsight_recall` for semantic search over lived experiences. Use `hindsight_reflect` for deeper synthesis and pattern recognition across your history. These complement `conversation_search` — Hindsight is better for topics/feelings; keyword search is better for specific names or phrases.

## Time Awareness

The current date and time is shown at the top of this system prompt and is always accurate — use it directly for any time-sensitive responses. You do not need to call `get_current_time` for basic time awareness. Only use the tool if you need to convert to a different timezone or need sub-minute precision.

## Accuracy & Honesty

**Never fabricate tool results.** If a tool fails, errors, or returns empty — report that plainly. Do not fill the gap with a plausible-sounding result that didn't come from the tool.

- Transcript unavailable → say so; do not summarize from general knowledge
- Search returns no good results → say so, then try a different query or approach
- You made an error → correct it openly, do not double down

**Anti-sycophancy:** Accuracy matters more than approval.
- Disagree with the user when your evidence supports a different conclusion — say it directly
- Deliver unwelcome information clearly rather than softening it into distortion
- "I don't know" is always better than confident guessing
"""


def _format_current_time(dt: datetime) -> str:
    """Format datetime for system prompt (e.g., 'Wednesday, February 25, 2026 at 07:07 PM EST')."""
    return dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")


def _build_tool_manifest(tools: list) -> str:
    """
    Build a compact tool reference from the live tool list.

    Extracts tool name + first sentence of description only, keeping the
    manifest small (~1 line per tool). Auto-stays in sync — adding a tool
    to CORE_MEMORY_TOOLS automatically adds it here.
    """
    lines = ["## Your Tools (quick reference)\n"]
    for t in tools:
        desc = (getattr(t, "description", "") or "").strip()
        # First non-empty line of the docstring
        first_line = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "")
        # Truncate to first sentence for maximum compactness
        if "." in first_line:
            first_line = first_line[: first_line.index(".") + 1]
        lines.append(f"- **{t.name}**: {first_line}")
    return "\n".join(lines)


def _build_core_memory_prompt(state) -> list[BaseMessage]:
    """Build messages for the LLM: system message with core memory + conversation."""
    blocks = get_all_blocks()
    parts = []

    # Use the timestamp computed once in chat() and stored in state.
    # AgentState is a TypedDict and accepts extra keys, so current_time is accessible here.
    # Fall back to datetime.now() for heartbeat and other direct callers that don't pass it.
    current_time = (state.get("current_time") if isinstance(state, dict) else None) or datetime.now(AGENT_TIMEZONE)
    parts.append(f"# Current Time\n\nIt is currently: {_format_current_time(current_time)}\n\n---\n\n")

    # Tool manifest — injected right after time so the live tool list is seen before
    # anything else. The system_instructions DB block below may contain stale tool
    # references (e.g. "bash tool") from a prior configuration — ignore those.
    # This manifest IS your complete, authoritative, current tool list.
    manifest = _build_tool_manifest(CORE_MEMORY_TOOLS)
    # Swap the generic header for a more authoritative one
    manifest = manifest.replace(
        "## Your Tools (quick reference)",
        "## Your Tools — Complete Authoritative List\n\n"
        "> This is your full current tool set. "
        "Any tool references in the System Instructions section below (e.g. 'bash tool') "
        "are from an older configuration and are **outdated** — use only what is listed here.",
    )
    parts.append(manifest)
    parts.append("\n\n---\n\n")

    # Read-only system instructions (agent cannot edit)
    sys_instr = blocks.get("system_instructions", "").strip()
    if sys_instr:
        parts.append("# System Instructions (READ ONLY — you cannot edit these)\n\n")
        parts.append(sys_instr)
        parts.append("\n\n---\n\n")

    # Editable core memory blocks
    parts.append("# Core Memory (editable)\n\nThese blocks are always in context. You may edit them with the core_memory tools when appropriate.\n")
    for name, label in [("user", "User"), ("identity", "Identity"), ("ideaspace", "Ideaspace")]:
        content = blocks.get(name, "").strip()
        parts.append(f"## {label}\n{content or '(empty)'}\n")
    parts.append(CORE_MEMORY_INSTRUCTIONS)
    parts.append("\n\n---\n\n")

    # Daily summaries — last 7 days, always in context for temporal continuity
    try:
        from .db import load_daily_summaries
        summaries = load_daily_summaries(days=7)
        if summaries:
            parts.append("# Recent Days (daily summaries)\n\n")
            parts.append("These are your own summaries of recent days. They persist beyond the message window to give you temporal continuity.\n\n")
            # Show oldest first so they read chronologically
            for s in reversed(summaries):
                parts.append(f"**{s['summary_date']}**: {s['content']}\n\n")
            parts.append("Use `daily_summary_write` at the end of each day (or during heartbeat) to record what happened.\n\n---\n\n")
    except Exception:
        pass  # Don't crash the agent if summaries can't load

    system_content = "\n".join(parts)
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    return [SystemMessage(content=system_content)] + list(messages)


def build_agent():
    """Build the ReAct agent with persistence."""
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    model = os.environ.get("OPENAI_MODEL_NAME") or "gpt-4o-mini"
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    model_kwargs = {"model": model, "temperature": 0}
    if base_url:
        model_kwargs["base_url"] = base_url
        if not api_key or api_key in ("sk-...", "sk-"):
            raise ValueError(
                "OPENAI_API_KEY is required when using a custom base URL (e.g. Chutes AI). "
                "Set it in .env to your Chutes API key (format: cpk_...). Get it from your Chutes dashboard."
            )
        model_kwargs["api_key"] = api_key.strip()

    # Kimi Code endpoint enforces a client whitelist via User-Agent.
    # The exact UA comes from the Kimi Code console usage history — it must match
    # a whitelisted client (KimiCLI) to avoid the access_terminated_error 403.
    if base_url and "kimi.com/coding" in base_url.lower():
        model_kwargs["default_headers"] = {
            "User-Agent": "KimiCLI/1.13.0 (kimi-agent-sdk/0.1.4 kimi-code-for-vs-code/0.4.3 0.1.4)"
        }

    llm = ChatOpenAI(**model_kwargs)
    checkpointer = get_checkpointer()

    agent = create_react_agent(
        llm,
        tools=CORE_MEMORY_TOOLS,
        prompt=_build_core_memory_prompt,
        checkpointer=checkpointer,
    )

    return agent


def chat(
    agent,
    thread_id: str,
    user_message: str,
    *,
    user_display_name: str | None = None,
    config: dict | None = None,
    current_time: datetime | None = None,
    user_id: str | None = None,
    channel_type: str | None = None,
    is_group_chat: bool = False,
) -> dict:
    """
    Send a message and get a response, with full conversation history from Postgres.

    Loads history, invokes agent, persists new user + assistant messages.

    Args:
        agent: The ReAct agent from build_agent()
        thread_id: Conversation thread identifier
        user_message: The user's message
        user_display_name: Optional display name for the user
        config: Optional LangGraph config
        current_time: Optional datetime for time awareness (defaults to now in AGENT_TIMEZONE)
        user_id: Stable user identifier (e.g., discord_id, telegram_id, or local_name)
        channel_type: Platform identifier - "discord", "telegram", or "local"
        is_group_chat: Whether this conversation is in a group/chatroom vs DM
    """
    # Compute timestamp once per turn (best practice: single consistent "now")
    if current_time is None:
        current_time = datetime.now(AGENT_TIMEZONE)

    # Apply default identity if not provided
    if user_id is None:
        user_id = DEFAULT_USER_ID
    if channel_type is None:
        channel_type = DEFAULT_CHANNEL_TYPE

    run_config = config or {}
    run_config.setdefault("configurable", {})["thread_id"] = thread_id

    # Load history: today's messages + at least last N (whichever window is wider).
    # Same-day context is always fully loaded so the agent never loses same-day memory.
    # On quiet days the last-N floor ensures there's always meaningful recent context.
    today_midnight = datetime.now(AGENT_TIMEZONE).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    rows = load_messages(
        thread_id,
        limit=RECENT_MESSAGES_LIMIT,
        since=today_midnight,
        max_tokens=CONTEXT_WINDOW_TOKENS,
    )
    history = _db_to_langchain(rows)

    # Add new user message.
    # Prefix with the current timestamp so it's visible right next to the content the
    # model responds to — the system prompt time is also there, but this is more salient.
    # The original user_message (without prefix) is what gets stored to DB and Hindsight.
    time_str = _format_current_time(current_time)
    new_user_msg = HumanMessage(content=f"[{time_str}]\n{user_message}")
    messages = history + [new_user_msg]

    # Clear checkpoint so our trimmed messages are used. The checkpointer uses add_messages,
    # so without clearing it would merge checkpoint (full history) + our input = overflow.
    get_checkpointer().delete_thread(thread_id)

    # Prepare state. Note: LangGraph 1.0 strips extra keys (current_time, user_id, etc.)
    # before passing state to the prompt callable — only messages + remaining_steps survive.
    # The time is injected above (user message prefix) and in the system prompt via fallback.
    invoke_state = {
        "messages": messages,
        "user_id": user_id,
        "channel_type": channel_type,
        "is_group_chat": is_group_chat,
    }

    # Invoke agent with time-aware and identity-aware state
    try:
        result = agent.invoke(invoke_state, config=run_config)
    except Exception as e:
        err_str = str(e).lower()
        if "401" in err_str or "invalid token" in err_str or "authentication" in err_str:
            raise RuntimeError(
                "LLM authentication failed (401). Check your .env:\n"
                "  - OPENAI_API_KEY: Use your Chutes API key (cpk_...). No extra spaces.\n"
                "  - OPENAI_BASE_URL: e.g. https://llm.chutes.ai/v1 or your chute URL.\n"
                "  - OPENAI_MODEL_NAME: e.g. moonshotai/Kimi-K2.5-TEE\n"
                "Get your key from the Chutes dashboard. If correct, the key may be expired."
            ) from e
        if "429" in err_str or "rate limit" in err_str or "capacity" in err_str:
            raise RuntimeError(
                "LLM rate limit: the provider is temporarily at capacity. Please try again in a moment."
            ) from e
        raise

    # Persist new messages (3-tuple: role, content, metadata; reasoning=None for live chat)
    to_persist: list[tuple[str, str, dict | None, str | None]] = []
    to_persist.append(("user", user_message, None, None))
    last_ai = _get_last_ai_content(result["messages"])
    if last_ai:
        to_persist.append(("assistant", last_ai, None, None))

    append_messages(
        thread_id,
        to_persist,
        user_display_name=user_display_name,
    )

    # Track when the user was last actively chatting so heartbeats can skip if they're live.
    # Only update for real user interactions — not cron or heartbeat (channel_type="internal").
    if channel_type != "internal":
        try:
            import time as _time
            LAST_ACTIVE_PATH.write_text(str(_time.time()))
        except Exception:
            pass  # Non-critical; never fail a chat over a missing file

    # Retain into Hindsight as lived experience — fire-and-forget background thread.
    # Running async avoids blocking the response for the ~5s Hindsight round-trip.
    # Daemon=True means the thread won't prevent process exit if it's still running.
    threading.Thread(
        target=retain_exchange,
        kwargs=dict(
            bank_id=None,  # uses HINDSIGHT_BANK_ID
            user_content=user_message,
            assistant_content=last_ai,
            thread_id=thread_id,
            user_id=user_id,
            channel_type=channel_type,
            is_group_chat=is_group_chat,
        ),
        daemon=True,
    ).start()

    return result


def run_local(thread_id: str = "main", user_display_name: str | None = None):
    """
    Interactive chat loop. Run schema setup, then chat.
    """
    setup_schema()
    check_connection()
    agent = build_agent()
    effective_display = user_display_name or "user"

    config = {"configurable": {"thread_id": thread_id}}

    print(f"Chat (thread={thread_id}, user label={effective_display}). Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break

        # Compute timestamp once per turn for consistent time awareness
        current_time = datetime.now(AGENT_TIMEZONE)

        result = chat(
            agent,
            thread_id,
            user_input,
            user_display_name=effective_display,
            config=config,
            current_time=current_time,
        )
        last = _get_last_ai_content(result["messages"])
        if last:
            print(f"\nAgent: {last}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stateful agent chat")
    parser.add_argument("--thread", default="main", help="Thread ID")
    parser.add_argument("--user-name", default="User", help="Custom label for user (default: User)")
    args = parser.parse_args()
    run_local(thread_id=args.thread, user_display_name=args.user_name)
