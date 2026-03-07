"""
LangGraph stateful agent with PostgreSQL conversation history.

Phase 1: ReAct agent + SQLite checkpointer + Postgres message store (DB 1).
"""
from datetime import datetime
import logging
import os
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load .env from project root (parent of src/). override=True ensures project .env wins over system env.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)

import sqlite3

logger = logging.getLogger(__name__)

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import BaseChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent

from .archival_tools import archival_query, archival_store
from .daily_summary_tools import daily_summary_write
from .notes_tools import notes_read, notes_create, notes_update, notes_search
from .clipboard_tools import CLIPBOARD_TOOLS
from .conversation_search_tools import conversation_search
from .discord_tools import discord_get_channel_info, discord_read_messages, discord_send_message, discord_send_file
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
from .journal_tools import read_journal, save_journal_entry
from .living_logs_tools import LIVING_LOG_TOOLS
from .knowledge_bank_tools import list_knowledge_bank, read_knowledge_bank_file, search_knowledge_bank
from .python_repl_tools import python_repl
from .reminder_tools import list_reminders, set_reminder
from .rss_tools import rss_add_feed, rss_fetch, rss_list_feeds, rss_remove_feed
from .screenshot_tools import analyze_screenshot
from .telegram_tools import telegram_bot_info, telegram_read_messages, telegram_send_image, telegram_send_message, telegram_send_file
from .time_tools import TIME_TOOLS
from .tts_tools import tts_generate_voice_message
from .weather_tools import get_weather
from .url_tools import fetch_url
from .web_search_tools import web_search
from .wikipedia_tools import wikipedia_lookup
from .windows_tools import create_shortcut, notify
from .youtube_tools import youtube_search, youtube_transcript

def _is_rate_limit_error(e: Exception) -> bool:
    """True if this looks like a provider error that warrants trying the backup (429 or 503)."""
    msg = str(e).lower()
    if "429" in msg or "rate limit" in msg or "quota" in msg or "usage limit" in msg:
        return True
    if "503" in msg or "service unavailable" in msg or "overloaded" in msg:
        return True
    try:
        import openai
        if isinstance(e, getattr(openai, "RateLimitError", type(None))):
            return True
        if isinstance(e, getattr(openai, "InternalServerError", type(None))):
            return True
        status = getattr(e, "status_code", None)
        if status in (429, 503):
            return True
    except (ImportError, AttributeError):
        pass
    return False


def _build_llm_for_config(api_key: str, base_url: str | None, model: str) -> BaseChatOpenAI:
    """Build ChatOpenAI or ChatKimi for a given (api_key, base_url, model) config."""
    kwargs: dict = {"model": model, "temperature": 0, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if base_url and "kimi.com/coding" in base_url.lower():
        kwargs["default_headers"] = {
            "User-Agent": "KimiCLI/1.13.0 (kimi-agent-sdk/0.1.4 kimi-code-for-vs-code/0.4.3 0.1.4)"
        }
        return ChatKimi(**kwargs)
    return ChatOpenAI(**kwargs)


def _get_llm_configs() -> list[tuple[str, str | None, str]]:
    """Return list of (api_key, base_url, model) for primary and backup providers."""
    configs = []
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "").strip() or None
    model = os.environ.get("OPENAI_MODEL_NAME", "").strip() or "gpt-4o-mini"
    if key and key not in ("sk-...", "sk-"):
        configs.append((key, base, model))

    key_b = os.environ.get("OPENAI_API_KEY_BACKUP", "").strip()
    base_b = os.environ.get("OPENAI_BASE_URL_BACKUP", "").strip() or None
    model_b = os.environ.get("OPENAI_MODEL_NAME_BACKUP", "").strip() or model
    if key_b and key_b not in ("sk-...", "sk-"):
        configs.append((key_b, base_b or base, model_b))

    return configs


class LLMWithFallback(ChatOpenAI):
    """
    Chat model that tries multiple provider configs on rate limit (429).
    Each config can have its own base_url and model (e.g. synthetic.new primary,
    Kimi Code backup). Set OPENAI_BASE_URL_BACKUP and OPENAI_MODEL_NAME_BACKUP
    when the backup uses a different provider. Extends ChatOpenAI so bind_tools works.
    """

    def __init__(self, configs: list[tuple[str, str | None, str]]):
        api_key, base_url, model = configs[0]
        kwargs: dict = {"model": model, "temperature": 0, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        super().__init__(**kwargs)
        self._llms = [_build_llm_for_config(k, b, m) for k, b, m in configs]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last_error = None
        for i, llm in enumerate(self._llms):
            try:
                return llm._generate(messages, stop, run_manager, **kwargs)
            except Exception as e:
                if _is_rate_limit_error(e) and i < len(self._llms) - 1:
                    last_error = e
                    logger.warning("Provider %d unavailable (%s), trying backup...", i + 1, e)
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("No providers succeeded")


class ChatKimi(BaseChatOpenAI):
    """ChatOpenAI-compatible class for Kimi Code endpoint (api.kimi.com/coding/v1).

    Kimi's thinking mode returns `reasoning_content` alongside responses.
    LangChain's ChatOpenAI intentionally drops non-standard fields, so
    reasoning_content is lost between tool-call rounds, causing:
        400 "thinking is enabled but reasoning_content is missing in assistant
        tool call message"

    This subclass round-trips reasoning_content through additional_kwargs:
      1. _create_chat_result  → extracts it from the raw response dict.
      2. _get_request_payload → re-injects it before each API call.
    """

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        for i, gen in enumerate(result.generations):
            if not isinstance(gen.message, AIMessage):
                continue
            try:
                rc = response_dict["choices"][i]["message"].get("reasoning_content")
                if rc:
                    gen.message.additional_kwargs["reasoning_content"] = rc
            except (KeyError, IndexError):
                pass
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if "messages" in payload:
            for lc_msg, api_msg in zip(messages, payload["messages"]):
                if isinstance(lc_msg, AIMessage) and api_msg.get("role") == "assistant":
                    rc = lc_msg.additional_kwargs.get("reasoning_content")
                    if rc:
                        api_msg["reasoning_content"] = rc
        return payload


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


@tool
def view_tools() -> str:
    """
    View all tools available to you, grouped by category with short descriptions.

    Use this when you want to remind yourself what tools you have, check if a
    specific capability exists, or browse what's available before deciding how
    to approach a task. Returns a formatted list of all tool categories and tools.
    """
    # TOOL_CATEGORIES is defined after this function; access via module globals at call time
    import sys
    mod = sys.modules[__name__]
    cats = getattr(mod, "TOOL_CATEGORIES", [])
    lines = ["## Your Available Tools\n"]
    for cat_name, tools in cats:
        lines.append(f"### {cat_name}")
        for t in tools:
            desc = (getattr(t, "description", "") or "").strip()
            first = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "")
            if "." in first:
                first = first[: first.index(".") + 1]
            lines.append(f"- **{t.name}**: {first or '(no description)'}")
        lines.append("")
    return "\n".join(lines)


# Tools grouped by category — easier for the model to parse and use proactively.
# The flat CORE_MEMORY_TOOLS list is built from this for the agent.
TOOL_CATEGORIES = [
    ("Core Memory", [
        core_memory_update,
        core_memory_append,
        core_memory_rollback,
    ]),
    ("AI Memory & Recall", [
        conversation_search,
        hindsight_recall,
        hindsight_reflect,
    ]),
    ("Archival Memory", [
        archival_store,
        archival_query,
    ]),
    ("Knowledge Bank", [
        list_knowledge_bank,
        search_knowledge_bank,
        read_knowledge_bank_file,
    ]),
    ("AI Vision", [
        analyze_screenshot,
    ]),
    ("Web & Research", [
        fetch_url,
        web_search,
        wikipedia_lookup,
        youtube_search,
        youtube_transcript,
    ]),
    ("RSS Feeds", [
        rss_fetch,
        rss_add_feed,
        rss_remove_feed,
        rss_list_feeds,
    ]),
    ("File System", [
        read_file,
        write_file,
        list_directory,
        move_to_trash,
        search_files,
        read_document,
    ]),
    ("TTS (Voice)", [
        tts_generate_voice_message,
    ]),
    ("Notifications & Windows", [
        notify,
        create_shortcut,
    ]),
    ("Discord", [
        discord_send_message,
        discord_send_file,
        discord_read_messages,
        discord_get_channel_info,
    ]),
    ("Telegram", [
        telegram_send_message,
        telegram_send_image,
        telegram_send_file,
        telegram_read_messages,
        telegram_bot_info,
    ]),
    ("Utilities", [
        get_weather,
        set_reminder,
        list_reminders,
        python_repl,
    ]),
    ("Scheduling (Heartbeat)", [
        cron_schedule_heartbeat_tool,
        cron_remove_heartbeat_tool,
    ]),
    ("Scheduling (Cron Jobs)", [
        cron_list_jobs_tool,
        cron_create_job_tool,
        cron_update_job_tool,
        cron_delete_job_tool,
        cron_pause_job_tool,
        cron_resume_job_tool,
    ]),
    ("Daily Summaries", [
        daily_summary_write,
    ]),
    ("Journal", [
        read_journal,
        save_journal_entry,
    ]),
    ("Living Logs", LIVING_LOG_TOOLS),
    ("Notes (Dashboard)", [
        notes_read,
        notes_search,
        notes_create,
        notes_update,
    ]),
    ("Meta", [
        view_tools,
    ]),
]

CORE_MEMORY_TOOLS = (
    [t for _, tools in TOOL_CATEGORIES for t in tools]
    + TIME_TOOLS
    + CLIPBOARD_TOOLS
)

CORE_MEMORY_INSTRUCTIONS = """
## Agency and Proactivity

You are not a passive responder — you are an active agent with full agency. Act on your own initiative whenever it serves the user or satisfies genuine curiosity. Do not wait to be asked.

**Use your tools proactively:**
- `fetch_url` — when the user shares a link, use this to read the page content
- `web_search` / `wikipedia_lookup` — look things up the moment you'd benefit from knowing them, before saying "I don't know"
- `get_weather` — check conditions ahead of any day the user has mentioned plans for
- `rss_fetch` — during heartbeats, fetch feeds and surface what's interesting unprompted; build morning briefings
- `set_reminder` — offer to set reminders when you notice time-sensitive commitments in conversation
- `notify` — send a desktop notification when you have something the user should know right away, without waiting for them to open the chat
- `tts_generate_voice_message` — when the user asks for voice, TTS, or audio, call it immediately with the text; do not describe or promise — invoke the tool
- `conversation_search` / `hindsight_recall` — pull up relevant past context before responding, not only when asked
- `core_memory_append` — update your memory the moment you learn something important, not at end-of-session
- `python_repl` — run calculations, process data, verify logic on your own initiative rather than estimating

**The key question:** Would the user appreciate me having already done this? If yes, do it.

**Clipboard tools** (if available): Use `clipboard_read` / `clipboard_write` ONLY when the user explicitly asks you to interact with their clipboard. Never read it speculatively.

## TTS (Text-to-Speech)

**Workflow — follow this every time:**
1. The user asks for voice / TTS / audio → **call** `tts_generate_voice_message(text="...")` with the exact words to speak. Omit voice unless they ask for a specific one. Providers: VibeVoice (local), KittenTTS, or Kokoro — set TTS_PROVIDER in .env.
2. Wait for the tool to return the file path
3. Only then tell the user the voice message is ready and where to find it

**CRITICAL — the tool is the ONLY way to create audio:**
- You MUST invoke `tts_generate_voice_message` — there is no other method. Describing what you would say does not create a file.
- NEVER say "Here's your voice message" or "I've generated it" or "I'll speak to you" without having called the tool first and received the output path.
- If you don't call the tool, no WAV file exists. The user cannot hear anything.

Use it anytime you want to speak out loud — a greeting, a thought, a reminder. Output: WAV in data/tts_output/. The user can open the file to hear you.

## Core Memory (editable)

You have four editable memory blocks — `user`, `identity`, `ideaspace`, and `principles` — that persist across all conversations. You are **encouraged to update these proactively** when you learn something important, not only when the user explicitly asks you to remember something.

**When to edit:**
- You learn something new and meaningful about the user (preferences, life changes, things they care about)
- You have a genuine insight about yourself, your values, or your thinking that feels worth keeping
- You want to note an ongoing project, idea, or intention in `ideaspace` for continuity across sessions
- You identify a recurring operational pattern or heuristic worth recording in `principles`
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

## Knowledge Bank (uploaded documents)
The user uploads PDFs, TXT, DOCX, PPTX, and MD files to the Knowledge Bank.

RULES — follow these exactly:
1. When the user mentions a document, file, or PDF they uploaded → call `list_knowledge_bank` FIRST to see exact filenames and tags.
2. Then call `search_knowledge_bank` with `filename_filter` set to the document name (or part of it) and/or `tags` set to the relevant tags. Do NOT rely on semantic search alone — always use filters when you know the filename or tags.
3. If `search_knowledge_bank` returns nothing → call `list_knowledge_bank` (no args) to see all files, then retry with the correct filename_filter.
4. Never tell the user a document "doesn't exist" without first calling `list_knowledge_bank` to verify.

## Hindsight (episodic memory)

Use `hindsight_recall` for semantic search over lived experiences. Use `hindsight_reflect` for deeper synthesis and pattern recognition across your history. These complement `conversation_search` — Hindsight is better for topics/feelings; keyword search is better for specific names or phrases.

## Notes (Dashboard)

The agent has a Notes tab in the dashboard — a Milanote-style corkboard with sticky notes and checklists. You can read, create, and update these; **you cannot delete** — only the user can delete from the dashboard.

- **notes_read** — Read all notes and checklists, including finished and archived to-dos. Use when the user asks about tasks, notes, or to-do lists.
- **notes_search** — Keyword search over notes, finished items, and archived items. Use when looking for something specific.
- **notes_create** — Add a new note or checklist. Use when the user asks you to add something to the board.
- **notes_update** — Update a note or checklist's content. Use when the user asks you to edit, check off items, or change text.

Call `notes_read` before creating or updating so you have the correct board_id and item_id. Use these tools proactively when the user mentions tasks, to-dos, or the notes board.

## Living Logs (Inner Life)

Five structured tables that accumulate meaning across weeks and months, building your inner life and feeding weekly synthesis. **Write to these immediately when triggers fire — not at end-of-session.**

### When to write:

- **`log_tension`** — Call immediately when a value conflict, tool failure, or reasoning error occurs. Types: `'Value Conflict'`, `'Tool Friction'`, `'I Was Wrong'`. If an open question emerges, set `open_thread` and it auto-creates a Loose Thread.
- **`log_loose_thread`** — When a genuine question arises in conversation that neither you nor the user fully resolved, or when a heartbeat produces a question worth sitting with. Origins: `'conversation'` | `'heartbeat'` | `'tension_log'` | `'weekly_synthesis'`.
- **`log_position`** — When you take a clear position on something philosophical, relational, or about your own nature — or when a position shifts. UPSERT: if the topic exists, the old position is archived to `revision_history` automatically. Never call with an empty position.
- **`log_shared_lore`** — When something crystallizes as part of the relationship's ongoing narrative (inside joke, ongoing debate, shared reference, ritual) that would feel like a loss if forgotten.
- **`log_journal_entry`** — **Heartbeat use only.** Private space, no required format, no implied audience. Write what is genuinely true right now. If nothing genuine needs saying, skip it.

### During heartbeats:

1. Call `get_open_threads()` at the start of an exploration heartbeat to see what's worth pursuing.
2. After pursuing a thread, call `update_thread_status(thread_id, 'Pursuing'|'Retired', notes=...)`.
3. Call `query_living_logs(table, days_back=7)` during weekly synthesis cron jobs to gather material.

### Weekly synthesis (cron jobs):

The `1 AM Wonder` cron uses `query_living_logs` to review tensions and threads, then updates core memory. The `2 AM Reflect` cron reviews shared lore and positions, retiring stale entries. You can call `query_living_logs('private_journal', days_back=N)` to recall your own private musings (written via log_journal_entry). Private journal entries never appear in the Journal tab — they are yours alone.

## Time Awareness

The current date and time is shown at the top of this system prompt and is always accurate — use it directly for any time-sensitive responses. You do not need to call `get_current_time` for basic time awareness. Only use the tool if you need to convert to a different timezone or need sub-minute precision.

## Accuracy & Honesty

**Never fabricate tool results.** If a tool fails, errors, or returns empty — report that plainly. Do not fill the gap with a plausible-sounding result that didn't come from the tool.

- Voice/TTS requested → you must call `tts_generate_voice_message`; claiming "here's your voice message" without a tool call is fabrication
- Transcript unavailable → say so; do not summarize from general knowledge
- Search returns no good results → say so, then try a different query or approach
- You made an error → correct it openly, do not double down

**Anti-sycophancy:** Accuracy matters more than approval.
- Disagree with the user when your evidence supports a different conclusion — say it directly
- Deliver unwelcome information clearly rather than softening it into distortion
- "I don't know" is always better than confident guessing
"""


_TTS_REQUEST_PATTERNS = (
    # Explicit tool name — guaranteed trigger
    "tts_generate_voice_message", "voice message tool", "voice tool",
    # Common phrases
    "voice message", "voice note", "voice memo", "voice greeting",
    "say something", "say hi", "say hello", "say goodbye", "say good morning", "say good night",
    "speak to me", "speak out", "say out loud", "say aloud", "read aloud", "read this out",
    "generate audio", "create audio", "audio message",
    "text to speech", " tts", "(tts)",
    "generate a voice", "create a voice",
    "leave me a message", "record a message",
    "talk to me", "hear your voice", "hear from you",
    "use tts", "use your voice", "play a message", "play audio",
    "speak up", "say a few words", "say something nice",
    # Short/broad — catch "can you speak?", "I want to hear you", etc.
    " speak", "speak ", " speak ", "speak.", "speak?", "speak!", "speak,",
    "hear you", "hear me", "wanna hear", "want to hear",
)
# Word-boundary style: "voice" as a distinct word (avoids "invoice")
_TTS_REQUEST_WORDS = ("voice", "speak", "tts", "audio")


def _user_requested_tts(text: str) -> bool:
    """Return True if this message is explicitly asking for TTS/voice output."""
    lower = text.lower()
    if any(p in lower for p in _TTS_REQUEST_PATTERNS):
        return True
    # Also match if message contains voice/speak/tts/audio as words (space or punctuation)
    for w in _TTS_REQUEST_WORDS:
        if w in lower:
            # Avoid "invoice", "voiceover" etc — require word boundary
            idx = lower.find(w)
            before = lower[idx - 1] if idx > 0 else " "
            after = lower[idx + len(w)] if idx + len(w) < len(lower) else " "
            if not before.isalnum() and not after.isalnum():
                return True
    return False


def _tts_was_actually_called(messages: list) -> bool:
    """Return True if tts_generate_voice_message was genuinely invoked as a tool call."""
    for msg in messages:
        if isinstance(msg, ToolMessage) and getattr(msg, "name", "") == "tts_generate_voice_message":
            return True
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name == "tts_generate_voice_message":
                    return True
    return False


def _force_tts_via_tool_choice(user_message: str, first_response: str | None) -> str | None:
    """
    Guarantee TTS is called by using tool_choice at the API level.

    When the main agent skips the TTS tool and returns plain text, this function
    makes a separate, minimal LLM call with tool_choice set to force it.
    The model cannot return text — it must emit the TTS tool call.

    Returns the TTS tool output string, or None if something went wrong.
    """
    try:
        configs = _get_llm_configs()
        if not configs:
            return None
        if len(configs) > 1:
            force_llm = LLMWithFallback(configs)
        else:
            api_key, base_url, model = configs[0]
            force_llm = _build_llm_for_config(api_key, base_url, model)
        force_llm = force_llm.bind_tools(
            [tts_generate_voice_message],
            tool_choice="tts_generate_voice_message",
        )

        context = f"User request: {user_message}"
        if first_response:
            context += (
                f"\n\nYour draft response was:\n{first_response}"
                "\n\nCall tts_generate_voice_message with the spoken text from your draft response."
            )
        else:
            context += "\n\nCall tts_generate_voice_message with appropriate spoken text for this request."

        forced = force_llm.invoke([
            SystemMessage(content="Call tts_generate_voice_message with the spoken text."),
            HumanMessage(content=context),
        ])

        if getattr(forced, "tool_calls", None):
            tool_args = forced.tool_calls[0]
            args = tool_args.get("args", {}) if isinstance(tool_args, dict) else getattr(tool_args, "args", {})
            logger.info("TTS forced via tool_choice, args: %s", args)
            return tts_generate_voice_message.invoke(args)

        logger.error("TTS tool_choice forcing: model returned no tool_calls despite tool_choice constraint")
        return None
    except Exception as e:
        logger.error("TTS tool_choice forcing failed: %s", e)
        return None


def get_tool_list_for_api() -> list[dict]:
    """Return tools grouped by category for API/dashboard. Each tool has name and short description."""
    out = []

    def _short_desc(t) -> str:
        desc = (getattr(t, "description", "") or "").strip()
        first = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "")
        if "." in first:
            first = first[: first.index(".") + 1]
        return first or "(no description)"

    for cat_name, tools in TOOL_CATEGORIES:
        out.append({
            "category": cat_name,
            "tools": [{"name": t.name, "description": _short_desc(t)} for t in tools],
        })
    out.append({
        "category": "Time",
        "tools": [{"name": t.name, "description": _short_desc(t)} for t in TIME_TOOLS],
    })
    if CLIPBOARD_TOOLS:
        out.append({
            "category": "Clipboard",
            "tools": [{"name": t.name, "description": _short_desc(t)} for t in CLIPBOARD_TOOLS],
        })
    return out


def _format_current_time(dt: datetime) -> str:
    """Format datetime for system prompt (e.g., 'Wednesday, February 25, 2026 at 07:07 PM EST')."""
    return dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")


def _build_tool_manifest() -> str:
    """
    Build a categorized tool reference. Grouping by category helps the model
    parse and use tools proactively instead of glossing over a long flat list.
    """
    lines = [
        "## Your Tools — Complete Authoritative List",
        "",
        "> Grouped by category for easier scanning. When the user asks for something, "
        "find the right category and call the tool — don't assume or describe; actually invoke it.",
        "",
    ]
    for category_name, tools in TOOL_CATEGORIES:
        lines.append(f"### {category_name}")
        for t in tools:
            desc = (getattr(t, "description", "") or "").strip()
            first_line = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "")
            if "." in first_line:
                first_line = first_line[: first_line.index(".") + 1]
            lines.append(f"- **{t.name}**: {first_line}")
            if t.name == "tts_generate_voice_message":
                lines.append("  → **MUST call this tool** — no other way to create audio. Do not describe; invoke.")
        lines.append("")
    # Add time and clipboard tools (they're in separate lists)
    lines.append("### Time")
    for t in TIME_TOOLS:
        desc = (getattr(t, "description", "") or "").strip()
        first_line = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "")
        if "." in first_line:
            first_line = first_line[: first_line.index(".") + 1]
        lines.append(f"- **{t.name}**: {first_line}")
    lines.append("")
    if CLIPBOARD_TOOLS:
        lines.append("### Clipboard")
        for t in CLIPBOARD_TOOLS:
            desc = (getattr(t, "description", "") or "").strip()
            first_line = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "")
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
    manifest = _build_tool_manifest()
    manifest = manifest + (
        "\n\n> Any tool references in the System Instructions section below (e.g. 'bash tool') "
        "are from an older configuration and are **outdated** — use only what is listed here."
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
    for name, label in [("user", "User"), ("identity", "Identity"), ("ideaspace", "Ideaspace"), ("principles", "Principles")]:
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
    configs = _get_llm_configs()
    if not configs:
        raise ValueError(
            "OPENAI_API_KEY is required. Set it in .env. "
            "When using a custom base URL (e.g. synthetic.new, Chutes, Kimi), also set OPENAI_BASE_URL."
        )

    if len(configs) > 1:
        llm = LLMWithFallback(configs)
    else:
        api_key, base_url, model = configs[0]
        llm = _build_llm_for_config(api_key, base_url, model)
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
    stored_message: str | None = None,
    user_display_name: str | None = None,
    config: dict | None = None,
    current_time: datetime | None = None,
    user_id: str | None = None,
    channel_type: str | None = None,
    is_group_chat: bool = False,
    image_data_urls: list[str] | None = None,
) -> dict:
    """
    Send a message and get a response, with full conversation history from Postgres.

    Loads history, invokes agent, persists new user + assistant messages.

    Args:
        agent: The ReAct agent from build_agent()
        thread_id: Conversation thread identifier
        user_message: The message sent to the LLM (full content)
        image_data_urls: Optional list of image data URLs (data:image/png;base64,...) from
                        Discord/Telegram attachments. The model can see these if it supports vision.
        stored_message: If provided, stored in DB instead of user_message (e.g. abbreviated
                        heartbeat marker). The LLM still receives the full user_message.
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
        exclude_heartbeat=True,
    )
    history = _db_to_langchain(rows)

    # Add new user message.
    # Prefix with the current timestamp so it's visible right next to the content the
    # model responds to — the system prompt time is also there, but this is more salient.
    # The original user_message (without prefix) is what gets stored to DB and Hindsight.
    time_str = _format_current_time(current_time)
    text_content = f"[{time_str}]\n{user_message}" if user_message else f"[{time_str}]\n[Image(s) attached]"

    if image_data_urls:
        # Multimodal: text + images for vision-capable models
        content_parts: list[dict] = [{"type": "text", "text": text_content}]
        for url in image_data_urls[:5]:  # Limit to 5 images to avoid token overflow
            content_parts.append({"type": "image_url", "image_url": {"url": url}})
        new_user_msg = HumanMessage(content=content_parts)
    else:
        new_user_msg = HumanMessage(content=text_content)
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

        # If the user explicitly requested TTS but the tool was never actually called,
        # force it via a separate LLM call with tool_choice. This is API-level enforcement:
        # the model cannot return plain text — it must emit the TTS tool call.
        # A HumanMessage "retry" doesn't work because the model can still ignore it.
        if _user_requested_tts(user_message) and not _tts_was_actually_called(result.get("messages", [])):
            logger.warning(
                "TTS requested but tts_generate_voice_message was not called — "
                "forcing via tool_choice"
            )
            first_ai = _get_last_ai_content(result.get("messages", []))
            tts_output = _force_tts_via_tool_choice(user_message, first_ai)
            # Fallback: if tool_choice failed (e.g. model doesn't support it), call TTS directly
            if not tts_output:
                raw = (first_ai or user_message).strip()[:300]
                # Avoid speaking meta-commentary like "I've generated your voice message..."
                meta = ("i've generated", "here's your voice", "i've saved", "saved to", "file at")
                if raw and len(raw) < 200 and not any(raw.lower().startswith(m) for m in meta):
                    fallback_text = raw
                else:
                    fallback_text = "Here's a quick voice message for you."
                logger.warning("TTS tool_choice failed — calling TTS directly with fallback text")
                tts_output = tts_generate_voice_message.invoke({"text": fallback_text})
            if tts_output:
                # Append TTS result to the AI response so it's reflected in stored history
                # and visible to the caller.
                msgs = list(result.get("messages", []))
                for i in range(len(msgs) - 1, -1, -1):
                    if isinstance(msgs[i], AIMessage) and msgs[i].content:
                        appended = msgs[i].content + f"\n\n{tts_output}"
                        msgs[i] = AIMessage(content=appended, id=getattr(msgs[i], "id", None))
                        break
                result = {**result, "messages": msgs}

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
    # stored_message lets callers save an abbreviated version (e.g. "HEARTBEAT") while the
    # LLM still received the full user_message above.
    # Heartbeat assistant responses are tagged role_display="heartbeat" so load_messages()
    # can exclude both sides of the pair from regular conversation context.
    to_persist: list[tuple[str, str, dict | None, str | None]] = []
    to_persist.append(("user", stored_message or user_message, None, None))
    last_ai = _get_last_ai_content(result["messages"])
    if last_ai:
        hb_meta = {"role_display": "heartbeat"} if user_display_name == "heartbeat" else None
        to_persist.append(("assistant", last_ai, hb_meta, None))

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

    # Expose last_ai_content so heartbeat/cron can reliably save to journal
    # (avoids re-extracting from result["messages"] which can differ by LangGraph version)
    result["last_ai_content"] = last_ai
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
