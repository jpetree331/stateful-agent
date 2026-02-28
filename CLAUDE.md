# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A local, stateful personal agent built with [LangGraph](https://github.com/langchain-ai/langgraph). Runs on Windows, remembers itself across sessions via core memory and long-term memory, and has 50+ tools covering web search, files, code execution, communications, scheduling, and more. Designed as a stable alternative to Letta/OpenClaw.

## Essential Commands

### Setup & Installation
```bash
# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Copy and configure environment variables
copy .env.example .env
# Edit .env — see Environment Variables section below
```

### Running the Agent

```bash
# Interactive chat (creates DB tables on first run)
python -m src.agent.graph

# With custom user label and thread
python -m src.agent.graph --user-name YourName --thread my-conversation

# Single heartbeat cycle (autonomous background thinking)
python -m src.agent.heartbeat

# Continuous heartbeat scheduler
python -m scripts.run_heartbeat_scheduler --interval 60
```

### Dashboard (Web UI)

```bash
# Terminal 1: Start FastAPI backend
python -m src.agent.api

# Terminal 2: Start Vite development server
cd dashboard && npm run dev
```

Then open http://localhost:5173

### Database Operations

```bash
# Check database connection
python scripts/check_db.py

# Import Letta backup conversation history
python scripts/import_letta_backup.py "path/to/backup.json" --thread main

# Import core memory from Letta
python scripts/import_core_memory.py "path/to/backup.json"
```

## Architecture Overview

**No Docker required for the agent itself.** It runs as a plain Python process on Windows.
Docker is only needed if running the optional Hindsight server (a separate component).

### Database Architecture (dual-DB)

1. **SQLite (`data/checkpoints.db`)**: LangGraph checkpointer for graph state snapshots between steps
2. **PostgreSQL (Railway)**: Long-term storage for:
   - Conversation history (`messages` table)
   - Core memory blocks (`core_memory` table with rollback history via `core_memory_history`)
   - System instructions (`system_instructions` table)
   - Archival facts (`archival.facts` schema)
   - Cron jobs (`cron_jobs` table)

### Letta-Style Bounded Context Window

Rather than loading all history into context (which caused 46-second responses with 415 Letta-imported messages), the agent uses a **paged recall architecture**:

- **Active context**: today's messages + last-N floor (whichever window is wider) — same-day messages always included
- **Tool messages excluded** from context at SQL level (`role != 'tool'`)
- **Full history** stays in PostgreSQL; agent uses `conversation_search` to retrieve older turns on demand
- Configurable via `RECENT_MESSAGES_LIMIT` env var (default: 30)

### Core Memory System

Four memory blocks always loaded into context:

1. **System Instructions** (read-only): Agent cannot edit; only modified via import scripts
2. **User** (editable): Information about the user
3. **Identity** (editable): Agent's identity and personality
4. **Ideaspace** (editable): Working memory for ongoing thoughts/tasks

**Tools**: `core_memory_update`, `core_memory_append`, `core_memory_rollback`

Core memory edits are **versioned with rollback support**. Each update saves the previous version to `core_memory_history`. Rollback restores one version at a time (destructive — removes the rolled-back entry).

**Key principle**: Always prefer `core_memory_append` over `core_memory_update`. Never delete unless factually wrong.

### Message Flow

1. User sends message via `chat()` in `graph.py`
2. System computes `today_midnight` and loads: today's messages + last-N floor (whichever is wider)
3. Checkpoint is cleared to avoid merge conflicts with trimmed history
4. ReAct agent invokes with `[SystemMessage(core_memory + instructions + tool_manifest)] + history + [new_user_msg]`
5. Agent calls tools as needed during execution
6. Final user + assistant messages are persisted to Postgres
7. Exchange is retained to Hindsight asynchronously (fire-and-forget daemon thread, ~5s savings per response)

### Heartbeat System

Autonomous background cycles (like OpenClaw/Letta):
- Prompt from `HEARTBEAT.txt` (path via `HEARTBEAT_PROMPT_PATH` env var)
- Skips automatically if the user was chatting within the last 5 minutes (`HEARTBEAT_SKIP_WINDOW_MINUTES`)
- Tracks last-active timestamp in `data/last_active.txt` (written after each real user chat)
- Can be scheduled via Windows Task Scheduler (`cron_schedule_heartbeat_tool`) or Python APScheduler

### Hindsight Integration

[Hindsight](https://github.com/vectorize-io/hindsight) provides episodic long-term memory:
- **Automatic retention**: Every exchange stored as lived experience (fire-and-forget thread)
- **Tools**: `hindsight_recall` (semantic search), `hindsight_reflect` (introspection)
- **Server**: Separate Docker container (see README.md for setup — only Docker usage in the project)
- **Configuration**: `HINDSIGHT_BASE_URL` and `HINDSIGHT_BANK_ID` in `.env`

## Full Tool List (42 tools; 44 with clipboard enabled)

### Memory
| Tool | Description |
|------|-------------|
| `core_memory_update` | Replace a core memory block (use sparingly) |
| `core_memory_append` | Append to a core memory block (preferred) |
| `core_memory_rollback` | Restore previous version of a memory block |
| `conversation_search` | Keyword + semantic search over full conversation history |
| `hindsight_recall` | Semantic search over episodic lived experience |
| `hindsight_reflect` | Synthesise patterns across long-term memory |
| `archival_store` | Store a curated fact in the archival fact store |
| `archival_query` | Search the archival fact store |

### Web & Research
| Tool | Description |
|------|-------------|
| `web_search` | Search via Tavily (default, AI-synthesised answer), Brave, or Exa |
| `wikipedia_lookup` | Fast encyclopedic lookup via Wikipedia REST API (no key needed) |
| `youtube_search` | Find YouTube videos by topic (uses Tavily/Brave, no YT API key needed) |
| `youtube_transcript` | Fetch captions from any public YouTube video (no YT API key needed) |

### RSS Feeds
| Tool | Description |
|------|-------------|
| `rss_fetch` | Fetch recent items from all subscribed feeds (ideal for morning briefings) |
| `rss_add_feed` | Subscribe to an RSS/Atom feed by URL |
| `rss_remove_feed` | Unsubscribe from a feed |
| `rss_list_feeds` | List all subscribed feeds |

Feed subscriptions stored in `data/rss_feeds.json`.

### Computation
| Tool | Description |
|------|-------------|
| `python_repl` | Execute Python code in an isolated subprocess |

### File System
| Tool | Description |
|------|-------------|
| `read_file` | Read a text file (50k char limit) |
| `write_file` | Write or append to a file (creates dirs automatically) |
| `list_directory` | List directory contents with sizes and dates |
| `move_to_trash` | Move a file to `~/Desktop/Agent_Trash/` (reversible) |
| `search_files` | Glob + optional content search |
| `read_document` | Read PDF or any text document (80k char limit) |

### Windows
| Tool | Description |
|------|-------------|
| `notify` | Send a Windows desktop toast notification |
| `create_shortcut` | Create a `.lnk` shortcut on desktop or any folder |
| `analyze_screenshot` | Capture screen and analyze with vision AI (returns text description) |

### Discord
| Tool | Description |
|------|-------------|
| `discord_send_message` | Send a message to a Discord channel via bot |
| `discord_read_messages` | Read recent messages from a Discord channel |
| `discord_get_channel_info` | Look up channel name, type, and server |

### Telegram
| Tool | Description |
|------|-------------|
| `telegram_send_message` | Send a text message via Telegram bot (Markdown supported) |
| `telegram_send_image` | Send an image file to Telegram |
| `telegram_read_messages` | Read incoming messages; advances offset to avoid duplicates |
| `telegram_bot_info` | Confirm bot is configured and see its username |

### Utilities
| Tool | Description |
|------|-------------|
| `get_weather` | Current weather + 3-day forecast via wttr.in (no API key needed) |
| `set_reminder` | In-process one-shot reminder via Windows toast notification |
| `list_reminders` | List all active in-process reminders |
| `get_current_time` | Current time in any timezone |
| `get_current_timestamp` | Unix timestamp |

### Scheduling
| Tool | Description |
|------|-------------|
| `cron_schedule_heartbeat_tool` | Create a Windows Task Scheduler entry for heartbeat |
| `cron_remove_heartbeat_tool` | Remove a scheduled heartbeat task |

### Clipboard (optional — requires `CLIPBOARD_ENABLED=true` in `.env`)
| Tool | Description |
|------|-------------|
| `clipboard_read` | Read current clipboard contents (only when the user explicitly asks) |
| `clipboard_write` | Write text to clipboard so the user can paste it |

## File Structure

```
.
├── src/
│   └── agent/
│       ├── graph.py                    # Main agent: ReAct loop, chat(), build_agent()
│       ├── db.py                       # Postgres connection, message CRUD, schema setup
│       ├── api.py                      # FastAPI server for dashboard (port 8000)
│       ├── heartbeat.py                # Autonomous heartbeat runner
│       ├── cron_scheduler.py           # APScheduler cron execution
│       ├── cron_jobs.py                # CRUD for cron_jobs PostgreSQL table
│       │
│       ├── core_memory.py              # Core memory block operations
│       ├── core_memory_tools.py        # Tools: core_memory_update/append/rollback
│       │
│       ├── hindsight.py                # Hindsight retention and API client
│       ├── hindsight_tools.py          # Tools: hindsight_recall, hindsight_reflect
│       │
│       ├── archival.py                 # Archival memory operations
│       ├── archival_tools.py           # Tools: archival_store, archival_query
│       │
│       ├── conversation_search_tools.py # Tool: conversation_search
│       │
│       ├── web_search_tools.py         # Tool: web_search (Tavily/Brave/Exa)
│       ├── youtube_tools.py            # Tools: youtube_search, youtube_transcript
│       ├── wikipedia_tools.py          # Tool: wikipedia_lookup
│       ├── rss_tools.py                # Tools: rss_fetch/add/remove/list
│       │
│       ├── python_repl_tools.py        # Tool: python_repl
│       │
│       ├── file_tools.py               # Tools: read/write/list/trash/search_files
│       ├── document_tools.py           # Tool: read_document (PDF + text)
│       │
│       ├── windows_tools.py            # Tools: notify, create_shortcut
│       ├── screenshot_tools.py         # Tool: analyze_screenshot (vision AI)
│       ├── clipboard_tools.py          # Tools: clipboard_read/write (opt-in via env)
│       │
│       ├── discord_tools.py            # Tools: discord_send/read/channel_info
│       ├── telegram_tools.py           # Tools: telegram_send/image/read/bot_info
│       │
│       ├── weather_tools.py            # Tool: get_weather
│       ├── reminder_tools.py           # Tools: set_reminder, list_reminders
│       ├── time_tools.py               # Tools: get_current_time, get_current_timestamp
│       └── cron_tools.py               # Tools: cron_schedule/remove_heartbeat_tool
│
├── scripts/
│   ├── import_letta_backup.py          # Import conversation history from Letta JSON
│   ├── import_core_memory.py           # Import core memory blocks from Letta
│   ├── check_db.py                     # Verify Postgres connection
│   └── run_heartbeat_scheduler.py      # Python-based heartbeat scheduler
│
├── dashboard/                          # React + Vite web UI
│   ├── src/App.jsx                     # Main chat interface
│   └── vite.config.js                  # Proxy: /api -> localhost:8000
│
├── data/
│   ├── checkpoints.db                  # SQLite: LangGraph state (auto-created)
│   ├── rss_feeds.json                  # Subscribed RSS feeds (auto-created)
│   ├── last_active.txt                 # Unix timestamp of last real user chat
│   ├── telegram_offset.txt             # Telegram update offset (avoids duplicates)
│   └── screenshots/                    # Saved screenshots (when save=True)
│
├── logs/
│   └── cron/cron.log                   # Cron execution log
│
├── .env                                # Configuration (see below)
├── requirements.txt                    # Python dependencies
├── CLAUDE.md                           # This file — guidance for Claude Code
├── README.md                           # User-facing quickstart
└── ARCHITECTURE.md                     # Original design rationale (historical)
```

## Environment Variables

```bash
# === LLM ===
OPENAI_API_KEY=           # Your API key (Chutes: cpk_..., OpenAI: sk-...)
OPENAI_BASE_URL=          # Custom endpoint (e.g. https://llm.chutes.ai/v1)
OPENAI_MODEL_NAME=        # Model name (e.g. moonshotai/Kimi-K2.5-TEE, gpt-4o)

# === Vision (for analyze_screenshot) ===
VISION_MODEL_NAME=        # Vision model (default: OPENAI_MODEL_NAME). Set to gpt-4o-mini
                          # if your main model doesn't support vision.
VISION_BASE_URL=          # Vision endpoint (default: OPENAI_BASE_URL)

# === Database ===
DATABASE_URL=             # PostgreSQL connection string (from Railway or local)

# === Memory ===
CONTEXT_WINDOW_TOKENS=200000   # Max token cap (safety; actual window is RECENT_MESSAGES_LIMIT)
RECENT_MESSAGES_LIMIT=40       # Active context window (turns)
HINDSIGHT_BASE_URL=http://localhost:8888
HINDSIGHT_BANK_ID=            # Your Hindsight memory bank ID
HINDSIGHT_USER_ID=            # Stable user ID for Hindsight retention

# === Agent Identity ===
AGENT_TIMEZONE=America/New_York
AGENT_LOCATION=City, ST        # Default location for weather (use "City, ST" or zip code)
DEFAULT_USER_ID=local:user
DEFAULT_CHANNEL_TYPE=local

# === Heartbeat ===
HEARTBEAT_PROMPT_PATH=              # Path to HEARTBEAT.txt
HEARTBEAT_SKIP_WINDOW_MINUTES=5     # Skip heartbeat if user chatted within N minutes

# === Web Search (pick at least one) ===
TAVILY_API_KEY=            # https://app.tavily.com — free 1k/month; default search mode
BRAVE_API_KEY=             # https://brave.com/search/api/
EXA_API_KEY=               # https://exa.ai

# === Communications ===
DISCORD_BOT_TOKEN=         # https://discord.com/developers/applications
DISCORD_CHANNEL_ID=        # Default channel ID (optional convenience)
TELEGRAM_BOT_TOKEN=        # From @BotFather on Telegram
TELEGRAM_CHAT_ID=          # Default chat ID (optional; run telegram_read_messages to find yours)

# === Optional Features ===
CLIPBOARD_ENABLED=         # Set to "true" to enable clipboard tools (off by default)

# === Tracing (optional) ===
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=         # LangSmith API key
```

## Key Design Patterns

### 1. Adding New Tools
1. Define the tool function in a new or existing `*_tools.py` file
2. Decorate with `@tool` from `langchain_core.tools`
3. Write a comprehensive docstring (agent reads this to understand when/how to use the tool)
4. Import and add to `CORE_MEMORY_TOOLS` list in `graph.py`
5. Optionally add usage guidance to `CORE_MEMORY_INSTRUCTIONS` in `graph.py`

The auto-generated tool manifest (`_build_tool_manifest`) injects a one-line reference for each tool into every system prompt automatically — no manual updates needed.

### 2. Conditional Tool Registration (clipboard pattern)

Tools can be gated by env var at import time:
```python
# In clipboard_tools.py
CLIPBOARD_TOOLS = [clipboard_read, clipboard_write] if CLIPBOARD_ENABLED else []

# In graph.py
CORE_MEMORY_TOOLS = [...] + CLIPBOARD_TOOLS
```

### 3. LangGraph Gotchas
- `create_react_agent` state: only `messages` + `remaining_steps` survive `invoke()` — extra keys silently dropped
- Always clear checkpoint before invoke to avoid merge conflicts with trimmed history
- Thread ID is the primary key for all conversations — same thread across restarts = continuity

### 4. Message Storage
- All messages: `thread_id`, `idx` (sequence), `role`, `content`
- `metadata` JSONB: includes `date_est`, `time_est`, optional `role_display`
- Tool messages stored with `role='tool'` but excluded from agent context at SQL level
- Cron messages stored in thread `"main"` with `role_display="cron"`

### 5. Error Handling
- Database connection failures raise clear `ValueError` with setup instructions
- LLM authentication failures (401) provide detailed `.env` debugging guidance
- Vision failures return actionable error with VISION_MODEL_NAME tip

## Development Workflow

1. **Make changes** to agent code
2. **Test imports**: `python -c "from src.agent.graph import CORE_MEMORY_TOOLS; print(len(CORE_MEMORY_TOOLS))"`
3. **Test interactively**: `python -m src.agent.graph --thread test`
4. **Check logs**: Enable LangSmith tracing for detailed execution traces
5. **Iterate**: State persists via checkpointer; restart anytime without losing context

## Dependencies

| Package | Purpose |
|---------|---------|
| `langgraph` | State management, persistence, ReAct agent |
| `langchain`, `langchain-core` | LLM abstractions, tools, message types |
| `langchain-openai` | ChatOpenAI (works with any OpenAI-compatible provider) |
| `psycopg[binary]` | PostgreSQL driver |
| `fastapi` + `uvicorn` | API server for dashboard |
| `hindsight-client` | Long-term episodic memory |
| `APScheduler` | Heartbeat scheduling |
| `httpx` | HTTP client (web search, weather, Discord, Telegram, Wikipedia) |
| `pypdf` | PDF reading |
| `youtube-transcript-api` | YouTube caption fetching (no YT API key needed) |
| `feedparser` | RSS/Atom feed parsing |
| `pyperclip` | Clipboard access (optional, gated by `CLIPBOARD_ENABLED`) |
| `Pillow` | Screenshot capture for `analyze_screenshot` |

## Project Status

- [x] Phase 1: Agent + SQLite checkpointer + Postgres conversation history
- [x] Phase 2: Core memory tools (update, append, rollback)
- [x] Phase 3: Hindsight integration (retain, recall, reflect)
- [x] Phase 3b: Heartbeat + cron scheduler + web dashboard
- [x] Phase 4a: Letta-style bounded context (last-N + today's messages + conversation_search)
- [x] Phase 4b: Tool suite — web search, Wikipedia, YouTube, RSS feeds, Python REPL, file system, PDF, weather, reminders, Windows notifications, shortcuts, screenshot+vision, Discord, Telegram, clipboard
- [ ] Phase 5: Docker deployment (optional — not needed for local use on Windows)
