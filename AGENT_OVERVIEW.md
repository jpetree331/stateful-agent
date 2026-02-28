# Personal AI Agent — Architecture Overview

A detailed overview of a **local, stateful personal AI agent** built with LangGraph. This document describes the architecture, design decisions, and technical components for developers who want to understand or replicate the system.

---

## What It Is

A personal AI agent that:
- Runs continuously on a local Windows PC (no cloud required for the agent itself)
- Remembers everything across sessions via layered memory systems
- Acts autonomously in the background between conversations
- Has 50+ tools covering research, computation, file management, communications, and system integration
- Exposes a web dashboard for chat and configuration
- Integrates with Discord (Gateway), Telegram (long-poll), Windows notifications, and RSS feeds
- Unified message thread across all channels — dashboard, Discord, and Telegram share the same conversation context

It was built as a self-hosted alternative to Letta/MemGPT and OpenClaw, using LangGraph as the production-grade backbone instead of more experimental frameworks.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | [LangGraph](https://github.com/langchain-ai/langgraph) (`create_react_agent`) |
| LLM | Any OpenAI-compatible provider (OpenAI, Chutes, Fireworks, etc.) |
| Short-term state | SQLite via `langgraph-checkpoint-sqlite` |
| Long-term storage | PostgreSQL (Railway or self-hosted) |
| Episodic memory | [Hindsight](https://github.com/vectorize-io/hindsight) (Docker container) |
| API server | FastAPI + Uvicorn |
| Web dashboard | React + Vite |
| HTTP client | httpx |
| Discord integration | discord.py (Gateway WebSocket) |
| Windows notifications | winotify |
| Screenshot | Pillow (PIL) |

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Local Windows PC                              │
│                                                                      │
│  ┌──────────────┐    ┌───────────────────────────────────────────┐  │
│  │  Web UI      │    │          FastAPI Backend (api.py)          │  │
│  │  React/Vite  │◄──►│  /chat  /messages  /cron  /memory        │  │
│  │  :5173       │    │                          :8000             │  │
│  └──────────────┘    └───────────────┬───────────────────────────┘  │
│                                      │                               │
│                          ┌───────────▼──────────┐                   │
│                          │   LangGraph Agent     │                   │
│                          │   (graph.py)          │                   │
│                          │                       │                   │
│                          │  ┌─────────────────┐  │                   │
│                          │  │  ReAct Loop     │  │                   │
│                          │  │  LLM ↔ Tools   │  │                   │
│                          │  └────────┬────────┘  │                   │
│                          └───────────┼───────────┘                   │
│                                      │                               │
│          ┌───────────────────────────┼──────────────────────┐        │
│          │                           │                       │        │
│  ┌───────▼──────┐          ┌─────────▼────────┐   ┌────────▼──────┐ │
│  │  SQLite DB   │          │  PostgreSQL       │   │  Hindsight    │ │
│  │  (checkpts)  │          │  (history, memory)│   │  (episodic)   │ │
│  └──────────────┘          └──────────────────┘   └───────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  Background Services (all in FastAPI lifespan)               │    │
│  │  • APScheduler — cron jobs stored in PostgreSQL              │    │
│  │  • Discord Gateway listener (discord.py WebSocket)           │    │
│  │  • Telegram long-poll listener (httpx getUpdates)            │    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Memory Architecture

This is the most distinctive part of the system. The agent uses **five separate but complementary memory layers**, each suited to a different type of knowledge.

### Layer 1: Core Memory (Always In Context)

Core memory is always loaded into every system prompt. It's a small set of structured blocks that give the agent persistent identity and working memory:

| Block | Purpose | Editable by agent? |
|-------|---------|-------------------|
| `system_instructions` | Behavioural guidelines and directives | No (read-only) |
| `user` | Information about the user | Yes |
| `identity` | The agent's personality, values, and self-concept | Yes |
| `ideaspace` | Working notes, ongoing tasks, current intentions | Yes |

Core memory is stored in PostgreSQL (`core_memory` table) with full version history. Every edit saves the previous version to `core_memory_history`, and the agent can roll back one step at a time using the `core_memory_rollback` tool. This prevents accidental data loss.

**Design principle**: The agent is strongly biased toward `core_memory_append` (additive) rather than `core_memory_update` (destructive replacement). Information is almost never deleted — only corrected when factually wrong.

### Layer 2: Conversation History (Paged Recall)

The full conversation history lives in PostgreSQL (`messages` table). However, loading all history into every prompt would be extremely slow and expensive — a problem encountered at scale with imported conversation archives.

The solution is a **Letta-style paged context window**:

```
Active context = max(today's messages, last N turns)
```

Specifically: the system computes midnight of the current day, then takes whichever window is wider — all of today's messages, or the last N turns. This guarantees:
- **Same-day continuity**: you never lose context for conversations happening today, even if they're long
- **Quiet-day floor**: on days with few messages, you still get meaningful context from recent history
- **Bounded cost**: the context window doesn't grow unboundedly with conversation age

Tool messages (bulky tool outputs) are excluded at the SQL level — they're stored for audit purposes but not injected into active context.

The agent uses `conversation_search` to retrieve older turns on demand: keyword search (PostgreSQL `ILIKE`) or semantic search (via Hindsight). This makes the full history accessible without paying to load it every turn.

### Layer 3: Daily Summaries (Temporal Context, Always In Context)

A dedicated `daily_summaries` PostgreSQL table stores short agent-written summaries of each day. The last 7 days of summaries are **always loaded into every system prompt**, giving the agent temporal continuity beyond the sliding message window.

Key design choices:
- **Agent-written**: the agent writes summaries in its own words via `daily_summary_write`, capturing what felt important rather than auto-generating from transcripts
- **Always present**: no search required — summaries are injected into the system prompt alongside core memory
- **Lightweight**: ~7 × 200 tokens ≈ 1,400 tokens total, a negligible context cost
- **Triggered by cron**: a nightly cron job prompts the agent to write today's summary before midnight

This layer bridges the gap between "what happened in the last 30 messages" and "what Hindsight can recall semantically" — it provides chronological narrative context without requiring retrieval.

### Layer 4: Hindsight — Episodic Memory

[Hindsight](https://github.com/vectorize-io/hindsight) is an external service that provides **long-term episodic memory** — memory of lived experience rather than raw transcripts.

Every user/assistant exchange is automatically retained to Hindsight as a lived experience, asynchronously (fire-and-forget background thread, so it doesn't add latency to responses).

The agent has two tools for accessing Hindsight:
- `hindsight_recall` — semantic similarity search over all past experiences
- `hindsight_reflect` — deeper synthesis and pattern recognition across memory

This complements `conversation_search`: Hindsight is better for thematic/emotional recall ("what have I felt about X"); keyword search is better for specific names, dates, or phrases.

### Layer 5: Archival Memory (Curated Facts)

A separate PostgreSQL schema (`archival.facts`) acts as the agent's curated long-term fact store. Unlike conversation history (which is raw transcript), archival memory is explicitly chosen by the agent — facts worth keeping in a structured, searchable form.

Tools: `archival_store`, `archival_query`.

### Memory System Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    Every System Prompt                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Core Memory (always present, ~1-3k tokens)               │   │
│  │  • System instructions (read-only)                       │   │
│  │  • User block (editable)                                 │   │
│  │  • Identity block (editable)                             │   │
│  │  • Ideaspace block (editable)                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Daily Summaries — last 7 days (always present, ~1-2k)   │   │
│  │  • Agent-written, chronological, temporal continuity     │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Active Conversation Window (today OR last-N turns)       │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Tool Manifest (auto-generated, one line per tool)        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

On demand (via tool calls):
  • conversation_search → older messages from PostgreSQL
  • hindsight_recall / hindsight_reflect → episodic memory
  • archival_query → curated fact store
```

---

## Agent Loop (Message Flow)

```
User message (dashboard, Discord, or Telegram)
     │
     ▼
load_messages()
  • Compute today_midnight (in agent's configured timezone)
  • Fetch: all today's messages OR last-N, whichever is wider
  • Exclude tool role messages at SQL level
     │
     ▼
Clear LangGraph checkpoint
  (prevents merge conflicts between trimmed history and stored state)
     │
     ▼
Build system prompt
  • _build_core_memory_prompt()
  • Injects: current time, tool manifest, core memory blocks,
             instructions, last 7 daily summaries
     │
     ▼
agent.invoke([SystemMessage] + history + [new_user_message])
  • ReAct loop: LLM reasons → selects tool → executes → observes → repeat
  • Continues until LLM produces a final answer
     │
     ▼
Persist to PostgreSQL
  • append_messages(user_message, assistant_response)
  • Metadata: UTC timestamp, EST formatted timestamp, display name, channel
     │
     ▼
Write last_active.txt (Unix timestamp)
  • Used by heartbeat to skip cycles during active chat
     │
     ▼
retain_exchange() → Hindsight (background daemon thread)
  • Non-blocking: ~5s savings per response
     │
     ▼
Return response to caller (API / Discord / Telegram)
```

---

## Multi-Channel Architecture

All channels share a single `"main"` conversation thread. The agent has the same memory, context, and history regardless of where a message arrives.

```
Dashboard (React)  ──────┐
Discord Gateway    ──────┼──► chat("main", ...) ──► PostgreSQL messages
Telegram long-poll ──────┘
Cron jobs          ──────┘
```

### Discord Gateway Listener

The Discord integration uses `discord.py`'s Gateway (persistent WebSocket connection) rather than REST polling:
- Bot appears **online** (green status) at all times while the API server is running
- Responds **immediately** when a message arrives — no polling interval
- Shows **typing indicator** while processing
- Reconnects automatically on disconnect
- Configured via `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` in `.env`

**Requirement**: In the Discord Developer Portal → Bot → Privileged Gateway Intents, the **Message Content Intent** must be enabled.

### Telegram Long-Poll Listener

The Telegram integration uses `getUpdates` with `timeout=30` (long-polling):
- Telegram holds the HTTP connection open for up to 30 seconds waiting for a new message
- Returns **immediately** when a message arrives — effectively instant response
- No wasteful short-interval polling
- On startup, skips any pending updates to avoid replying to old messages
- Verifies bot token via `getMe` before entering the poll loop
- Configured via `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

---

## Tool System

The agent has **50+ tools**, all implemented as LangChain `@tool`-decorated functions.

A key design choice: an **auto-generated tool manifest** is injected into every system prompt. `_build_tool_manifest()` extracts the tool name and first sentence of each docstring from the live tool list. It auto-stays in sync — adding a tool to `CORE_MEMORY_TOOLS` automatically adds it to the manifest with no manual work.

### Tool Categories

**Memory tools** — `core_memory_update/append/rollback`, `conversation_search`, `hindsight_recall/reflect`, `archival_store/query`, `daily_summary_write`

**Web & research** — `web_search` (Tavily/Brave/Exa), `wikipedia_lookup` (REST, no key), `youtube_search`, `youtube_transcript` (both use no YouTube API key)

**RSS feeds** — `rss_fetch`, `rss_add_feed/remove/list`. Feed subscriptions stored in a local JSON file. Designed for heartbeat morning briefings.

**Computation** — `python_repl` runs code in an isolated child subprocess (same venv), with a 30-second timeout.

**File system** — `read_file`, `write_file`, `list_directory`, `search_files`, `move_to_trash` (soft-delete to a named trash folder), `read_document` (PDF + text via pypdf)

**Windows integration**:
- `notify` — desktop toast notifications via [`winotify`](https://github.com/versa-syahptr/winotify), which properly registers an AppUserModelID on first use. The WinRT API silently drops notifications from unregistered AUMIDs; winotify solves this by creating a Start Menu shortcut.
- `create_shortcut` — `.lnk` files via WScript.Shell COM through PowerShell
- `analyze_screenshot` — captures all monitors, resizes to 1920×1200 max, base64-encodes, calls a vision-capable LLM inline, returns text analysis

**Communications**:
- `discord_send_message/read_messages/get_channel_info` — agent-initiated Discord REST API v10 calls (separate from the inbound Gateway listener)
- `telegram_send_message/send_image/read_messages/bot_info` — agent-initiated Telegram Bot API calls; `telegram_read_messages` uses offset persistence to avoid duplicate reads

**Utilities** — `get_weather` (wttr.in JSON, no key), `set_reminder/list_reminders` (threading.Timer + Windows toast), `get_current_time/timestamp`

**Scheduling**:
- `cron_schedule_heartbeat_tool/cron_remove_heartbeat_tool` — wraps Windows Task Scheduler via PowerShell for the heartbeat process
- `cron_list/create/update/delete/pause/resume_job_tool` — full CRUD for the dashboard cron job system (APScheduler + PostgreSQL). The agent can manage its own scheduled tasks without user intervention.

**Clipboard** (optional, env-gated) — `clipboard_read/write` via pyperclip; only registered when `CLIPBOARD_ENABLED=true` in environment

### Conditional Tool Registration

Tools that should be opt-in use a pattern where the module exports either the real tools or an empty list based on an environment variable, checked at import time:

```python
# In clipboard_tools.py
CLIPBOARD_TOOLS = [clipboard_read, clipboard_write] if CLIPBOARD_ENABLED else []

# In graph.py
CORE_MEMORY_TOOLS = [...base tools...] + CLIPBOARD_TOOLS
```

---

## Heartbeat System (Autonomous Background Cycles)

The agent can run without user interaction — "heartbeat" cycles that fire on a schedule.

A heartbeat is simply a regular call to `chat()` with a special prompt (loaded from a configurable text file) instead of a user message. The agent has full tool access during heartbeats and can: check RSS feeds and summarise news, send notifications, update memory, schedule reminders, reflect on recent events, write daily summaries, and proactively reach out via Discord or Telegram.

**Shared context**: Heartbeats use the same `"main"` thread as regular conversations. The agent wakes up with full access to recent conversation history and daily summaries — not a blank slate.

**Skip logic**: After each real user chat, the agent writes a Unix timestamp to `data/last_active.txt`. The heartbeat runner reads this and skips the cycle if the user was active within a configurable window (default: 5 minutes). This prevents heartbeats from interrupting or duplicating active conversations.

**Scheduling options**:
1. **APScheduler cron jobs** — configured via the dashboard UI or agent tools (`cron_create_job_tool`). Jobs are stored in PostgreSQL and survive restarts. The APScheduler runs inside the FastAPI lifespan.
2. **Python APScheduler script** — `run_heartbeat_scheduler.py`, a long-running process. Interval configurable via `--interval` CLI flag.
3. **Windows Task Scheduler** — the agent can create/remove Task Scheduler entries using `cron_schedule_heartbeat_tool`, which generates and runs PowerShell commands.

---

## Database Schema

### PostgreSQL Tables

```sql
-- Full conversation history
messages (
  id SERIAL PRIMARY KEY,
  thread_id TEXT NOT NULL,       -- conversation identifier ("main", etc.)
  idx INTEGER NOT NULL,          -- sequence number within thread
  role TEXT NOT NULL,            -- 'user', 'assistant', 'tool'
  content TEXT,
  reasoning TEXT,                -- for imported Letta backups
  metadata JSONB,                -- {date_est, time_est, role_display, channel, ...}
  created_at TIMESTAMPTZ DEFAULT NOW()
)

-- Core memory blocks (user, identity, ideaspace, system_instructions)
core_memory (
  block_type TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ DEFAULT NOW()
)

-- Version history for core memory (enables rollback)
core_memory_history (
  id SERIAL PRIMARY KEY,
  block_type TEXT NOT NULL,
  content TEXT NOT NULL,
  version INTEGER NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
)

-- Agent-written daily summaries (last 7 always in context)
daily_summaries (
  id SERIAL PRIMARY KEY,
  summary_date DATE NOT NULL UNIQUE,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
)

-- Curated fact store
archival.facts (
  id SERIAL PRIMARY KEY,
  content TEXT NOT NULL,
  category TEXT,                 -- optional tag for filtering
  created_at TIMESTAMPTZ DEFAULT NOW()
  -- search is full-text ILIKE, not vector/semantic
)

-- Dashboard cron jobs (APScheduler source of truth)
cron_jobs (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  instructions TEXT NOT NULL,    -- full prompt sent to agent when job fires
  timezone TEXT NOT NULL DEFAULT 'America/New_York',
  schedule_days INTEGER[],       -- 0=Mon..6=Sun; NULL for one-time jobs
  schedule_time TEXT,            -- e.g. "7:00 PM"
  run_date DATE,                 -- for one-time jobs
  is_one_time BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT DEFAULT 'active',  -- 'active' | 'paused'
  created_by TEXT NOT NULL,      -- 'user' | 'agent'
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  last_run_at TIMESTAMPTZ,
  last_run_status TEXT,          -- 'success' | 'error' | 'skipped'
  last_run_error TEXT,
  run_count INTEGER DEFAULT 0
)
```

### SQLite (LangGraph Checkpointer)

`data/checkpoints.db` — managed entirely by LangGraph. Stores graph state snapshots between agent steps, enabling durable execution (the agent can resume mid-run after a crash). The checkpoint is **cleared before each invocation** to prevent merge conflicts with the trimmed conversation history loaded from PostgreSQL.

---

## Proactivity Design

The agent is explicitly instructed to be **proactive rather than reactive**. Key design choices that enable this:

1. **Heartbeat cycles** — the agent acts without being messaged
2. **Agency instructions in system prompt** — the system prompt explicitly lists tools the agent should use without being asked: looking things up before saying "I don't know", updating memory immediately when something important is learned, sending notifications for time-sensitive information
3. **Fire-and-forget async** — Hindsight retention runs in a background thread so responsiveness is never sacrificed for memory operations
4. **Tool manifest in every prompt** — the agent always has a reminder of what it can do, making spontaneous tool use more likely
5. **Desktop notifications** — `notify` lets the agent push information to the user without waiting for the chat window to be open
6. **Self-managed cron jobs** — the agent can create, edit, and delete its own scheduled tasks without user intervention

---

## API Design

The FastAPI backend exposes these endpoints:

```
POST /chat                        — Send message, get response
GET  /messages                    — Load conversation history (thread_id, limit params)
GET  /core-memory                 — Read all memory blocks
POST /core-memory/{block}         — Update a memory block

GET  /cron/jobs                   — List scheduled jobs (optional status filter)
POST /cron/jobs                   — Create a job (recurring or one-time)
GET  /cron/jobs/{id}              — Get a single job
PUT  /cron/jobs/{id}              — Update a job
DELETE /cron/jobs/{id}            — Delete a job
POST /cron/jobs/{id}/pause        — Pause a job
POST /cron/jobs/{id}/resume       — Resume a paused job
POST /cron/jobs/{id}/clone        — Clone a job
GET  /cron/timezones              — List available timezones

GET  /health                      — Health check
```

The React dashboard communicates with this API, polls for new messages every 10 seconds, and displays cron and heartbeat messages with a distinct visual style. CORS origins are configurable via `CORS_ORIGINS` env var for remote dashboard deployments.

---

## Design Decisions and Trade-offs

### Why LangGraph instead of raw LangChain agents?

LangGraph provides production-grade checkpointing and durable execution out of the box. If the process crashes mid-reasoning, it can resume from the last checkpoint. The SQLite checkpointer requires zero infrastructure.

### Why PostgreSQL for conversation history instead of the LangGraph checkpointer?

The LangGraph checkpointer stores binary graph state snapshots — not human-readable, and not easily queryable. PostgreSQL gives full SQL access to conversation history: keyword search, metadata filtering, pagination, and import/export. The two databases serve different purposes.

### Why the "paged recall" context window?

Loading full conversation history into every prompt worked fine during development but became unworkable after importing a large archive (~415 messages with tool call artifacts = 195k tokens = 46-second response times). The paged approach cuts typical context to ~3-5k tokens while keeping the full history accessible on demand.

### Why daily summaries instead of more semantic memory?

Daily summaries give **temporal narrative context** that semantic search doesn't capture well — the shape of a week, what was being worked on, the emotional arc of recent days. They're always present (no search required), agent-authored (capturing what the agent found significant rather than auto-generated summaries), and cheap (~1,400 tokens for 7 days).

### Why fire-and-forget for Hindsight retention?

The Hindsight API call takes ~5 seconds. Running it synchronously would add 5 seconds to every response. Since retention is eventually consistent by nature — the conversation was already logged to PostgreSQL — the tradeoff is sound. A daemon thread means the process won't block on exit either.

### Why Discord Gateway instead of REST polling?

REST polling (e.g. every 5 seconds) burns API quota when there's no activity, can't set the bot's online status, and has a 5-second maximum response latency. The Gateway WebSocket receives push events immediately, allows setting `Status.online`, and is Discord's recommended approach for bots. Requires the `discord.py` library but has no poll-interval configuration complexity.

### Why Telegram long-polling instead of webhooks?

Webhooks require a publicly accessible HTTPS endpoint, which a local PC doesn't have without a tunnel service. Long-polling (`getUpdates?timeout=30`) is Telegram's official recommendation for local bots — it holds the connection open for up to 30 seconds waiting for new messages, making it effectively instant without needing any inbound connectivity.

### Why winotify for Windows notifications instead of PowerShell WinRT?

The WinRT `ToastNotificationManager.CreateToastNotifier(appId)` call silently drops notifications when the AppID isn't registered in Windows — it returns success but never shows the toast. This happens whenever the AppID is an arbitrary string not registered in the Start Menu. `winotify` solves this by creating a Start Menu shortcut with a proper AppUserModelID on first use, exactly as every real Windows desktop app does.

### Why not Docker for the agent?

Docker adds infrastructure complexity (volumes, networking, startup order, image builds) with no meaningful benefit for a single-machine personal agent. The agent is a Python process, PostgreSQL is on a managed cloud service (Railway), and SQLite is a local file. These components don't need containerization. Docker is only used for the Hindsight server, which is a third-party component distributed as a container image.

---

## Extending the Agent

### Adding a new tool

1. Create a function in `src/agent/*_tools.py`, decorated with `@tool` from `langchain_core.tools`
2. Write a detailed docstring — the agent reads this to understand when and how to use the tool
3. Import and add to `CORE_MEMORY_TOOLS` in `graph.py`
4. The tool manifest updates automatically — no other changes needed

### Adding a new memory type

Add a new table to PostgreSQL, create accessor functions in a `*_tools.py` file, and optionally inject relevant content into `_build_core_memory_prompt()`.

### Changing the LLM provider

Update `OPENAI_BASE_URL` and `OPENAI_MODEL_NAME` in `.env`. The agent uses `ChatOpenAI` which accepts any OpenAI-compatible endpoint. For vision features, ensure the configured model supports image inputs.

### Adding a new platform integration

Both Discord and Telegram follow the same pattern:
- **Outbound tools**: `@tool`-decorated functions that call the platform's REST API, added to `CORE_MEMORY_TOOLS`
- **Inbound listener**: an asyncio task started in the FastAPI lifespan that receives messages and calls `chat("main", ...)`

The same pattern works for Slack, WhatsApp (via API), SMS (Twilio), etc.

---

## File Layout

```
.
├── src/agent/
│   ├── graph.py                    # Core: agent loop, chat(), memory prompt
│   ├── db.py                       # PostgreSQL: CRUD, schema, load_messages()
│   ├── api.py                      # FastAPI server + lifespan (starts all services)
│   ├── heartbeat.py                # Autonomous heartbeat runner
│   ├── core_memory.py/.tools.py    # Core memory blocks + tools
│   ├── hindsight.py/.tools.py      # Episodic memory + tools
│   ├── archival.py/.tools.py       # Curated fact store + tools
│   ├── daily_summary_tools.py      # daily_summary_write tool
│   ├── conversation_search_tools.py
│   ├── discord_listener.py         # Gateway WebSocket listener (discord.py)
│   ├── discord_tools.py            # Agent-initiated Discord REST tools
│   ├── telegram_listener.py        # Long-poll inbound listener
│   ├── telegram_tools.py           # Agent-initiated Telegram REST tools
│   ├── cron_jobs.py                # PostgreSQL CRUD for cron_jobs table
│   ├── cron_scheduler.py           # APScheduler integration
│   ├── cron_tools.py               # Agent tools for cron management
│   ├── web_search_tools.py         # Tavily / Brave / Exa
│   ├── youtube_tools.py            # Search + transcript (youtube-transcript-api v1.x)
│   ├── wikipedia_tools.py          # REST lookup
│   ├── rss_tools.py                # Feed subscriptions
│   ├── python_repl_tools.py        # Subprocess code execution
│   ├── file_tools.py               # File system
│   ├── document_tools.py           # PDF + text reader
│   ├── windows_tools.py            # Notifications (winotify), shortcuts
│   ├── screenshot_tools.py         # Screen capture + vision
│   ├── clipboard_tools.py          # Optional clipboard access
│   ├── weather_tools.py            # wttr.in
│   ├── reminder_tools.py           # threading.Timer reminders
│   └── time_tools.py
├── scripts/
│   ├── run_heartbeat_scheduler.py  # APScheduler-based heartbeat loop
│   └── import_*.py                 # One-time migration scripts
├── dashboard/                      # React + Vite
├── data/                           # Runtime state (SQLite, RSS feeds, offsets)
└── .env.example                    # All configurable environment variables
```
