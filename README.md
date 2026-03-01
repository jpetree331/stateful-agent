# Stateful LangGraph Agent

A local, stateful personal agent built with [LangGraph](https://github.com/langchain-ai/langgraph). Runs on Windows (and Linux/Mac with minor adjustments), remembers itself across sessions via a 5-layer memory system, and has 50+ tools covering web search, file system, code execution, Discord, Telegram, screenshot vision, RSS feeds, cron scheduling, and more.

**In-game chat overlay** — Chat with your agent while gaming. Full memory and context, same unified thread as Discord, Telegram, and the dashboard. No alt-tabbing.

Designed as an open, hackable alternative to Letta/OpenClaw. Built for people who want a real stateful AI companion running locally on their PC — fully configurable, no monthly SaaS fees.

---

## What It Does

- **Remembers you across sessions** — Core memory blocks (user profile, identity, ideaspace) always in context
- **Learns from experience** — Hindsight episodic memory retains every conversation as lived experience
- **Acts autonomously** — Heartbeat system wakes the agent periodically for independent work
- **Manages scheduled tasks** — Full cron job system with a dashboard UI
- **Communicates proactively** — Discord Gateway + Telegram long-poll so it's always listening
- **Runs on your PC** — File access, clipboard, screenshot analysis, Windows notifications
- **In-game overlay** — Always-on-top chat + screenshot capture for gaming (Electron)
- **Searches the web** — Brave/Tavily search, Wikipedia, YouTube transcripts, RSS feeds

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [PostgreSQL Setup (Railway)](#postgresql-setup-railway)
6. [Hindsight Memory Setup](#hindsight-memory-setup)
7. [Running the Agent](#running-the-agent)
8. [Dashboard (Web UI)](#dashboard-web-ui)
9. [In-Game Overlay](#in-game-overlay)
10. [Heartbeat / Autonomous Mode](#heartbeat--autonomous-mode)
11. [Discord Integration](#discord-integration)
12. [Telegram Integration](#telegram-integration)
13. [Memory Architecture](#memory-architecture)
14. [Tool Reference](#tool-reference)
15. [Environment Variables Reference](#environment-variables-reference)
16. [Advanced Configuration](#advanced-configuration)
17. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/yourname/stateful-agent
cd stateful-agent

# 2. Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/Mac
# Edit .env — at minimum set DATABASE_URL and OPENAI_API_KEY

# 4. Start chatting
python -m src.agent.graph
```

> **Minimum requirements to get started:** a PostgreSQL database (free on Railway) and an LLM API key (OpenAI or compatible).

---

## Prerequisites

| Requirement | Where to get it | Notes |
|-------------|----------------|-------|
| Python 3.11+ | [python.org](https://www.python.org/downloads/) | 3.12 recommended |
| PostgreSQL | [Railway (free tier)](#postgresql-setup-railway) | For conversation history & memory |
| LLM API key | [OpenAI](https://platform.openai.com/) or [Chutes AI](https://chutes.ai/) | Any OpenAI-compatible API works |
| Node.js 18+ | [nodejs.org](https://nodejs.org/) | Only for the dashboard UI |

**Optional (for full feature set):**
- Docker — for Hindsight episodic memory server
- Discord bot token — for Discord Gateway integration
- Telegram bot token — for Telegram integration
- Brave Search API key — for web search tool

---

## Installation

```bash
# Clone the repository
git clone https://github.com/yourname/stateful-agent
cd stateful-agent

# Create and activate virtual environment
python -m venv .venv

# Windows:
.venv\Scripts\activate

# Linux/Mac:
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Set up environment file
copy .env.example .env   # Windows
cp .env.example .env     # Linux/Mac

# Edit .env with your configuration
```

---

## Configuration

Edit `.env` with your values. The essential ones to get started:

```bash
# PostgreSQL connection string (required)
DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/railway

# LLM API key (required)
OPENAI_API_KEY=sk-...

# Optional: custom model/endpoint
OPENAI_BASE_URL=https://your-chute.chutes.ai/v1
OPENAI_MODEL_NAME=kimi-k-2.5

# Your display name in the dashboard
USER_DISPLAY_NAME=YourName
```

See [Environment Variables Reference](#environment-variables-reference) for the full list.

---

## PostgreSQL Setup (Railway)

The agent uses PostgreSQL for conversation history, core memory, cron jobs, and daily summaries. [Railway](https://railway.app/) provides a free tier that works perfectly.

### Step 1: Create a Railway Account

1. Go to [railway.app](https://railway.app/) and sign up (free)
2. Create a new project

### Step 2: Add a PostgreSQL Database

1. In your Railway project, click **+ New** → **Database** → **PostgreSQL**
2. Wait for provisioning (about 30 seconds)

### Step 3: Get the Connection String

1. Click on the PostgreSQL service
2. Go to **Connect** tab
3. Copy the **Postgres URL** (starts with `postgresql://postgres:...`)
4. Paste it into your `.env` as `DATABASE_URL`

```bash
DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/railway
```

### Step 4: Verify the Connection

```bash
python scripts/check_db.py
```

Expected output: `✓ Connected to PostgreSQL successfully`

> **Note:** The database schema is created automatically on first run — no manual SQL setup needed.

---

## Hindsight Memory Setup

[Hindsight](https://github.com/vectorize-io/hindsight) provides deep episodic memory — the agent retains every conversation as a lived experience and can recall and reflect on them semantically.

This is **optional but highly recommended** for the best agent experience. Without Hindsight, the agent still works but can only search conversation history via keyword search.

### Option A: Local Docker (Recommended)

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

#### Step 1: Get an LLM API Key for Hindsight

Hindsight needs its own LLM access for generating memory embeddings. We recommend [Chutes AI](https://chutes.ai/) (free tier available):

1. Sign up at [chutes.ai](https://chutes.ai/)
2. Create a new "Chute" with the `gpt-oss-120b` model (or any compatible model)
3. Copy your API key and endpoint URL

#### Step 2: Run the Hindsight Docker Container

```bash
docker run -d \
  --name hindsight \
  --restart unless-stopped \
  -p 8888:8888 \
  -p 9999:9999 \
  -v hindsight_data:/data \
  -e HINDSIGHT_API_LLM_PROVIDER=openai \
  -e HINDSIGHT_API_LLM_BASE_URL=https://your-chute.chutes.ai/v1 \
  -e HINDSIGHT_API_LLM_MODEL=openai/gpt-oss-120b-TEE \
  -e HINDSIGHT_API_LLM_API_KEY=your-chutes-api-key \
  ghcr.io/vectorize-io/hindsight:latest
```

**Using standard OpenAI instead of Chutes:**
```bash
docker run -d \
  --name hindsight \
  --restart unless-stopped \
  -p 8888:8888 \
  -p 9999:9999 \
  -v hindsight_data:/data \
  -e HINDSIGHT_API_LLM_PROVIDER=openai \
  -e HINDSIGHT_API_LLM_MODEL=gpt-4o-mini \
  -e HINDSIGHT_API_LLM_API_KEY=sk-your-openai-key \
  ghcr.io/vectorize-io/hindsight:latest
```

#### Step 3: Verify Hindsight is Running

```bash
curl http://localhost:8888/health
# Expected: {"status":"ok"} or similar
```

#### Step 4: Configure in .env

```bash
HINDSIGHT_BASE_URL=http://localhost:8888
HINDSIGHT_BANK_ID=my-agent-memory
HINDSIGHT_ENABLED=true
```

#### Step 5: Create a Memory Bank

The agent will automatically create the memory bank on first use. Or create it manually:

```bash
curl -X POST http://localhost:8888/banks \
  -H "Content-Type: application/json" \
  -d '{"bank_id": "my-agent-memory", "description": "Agent memory bank"}'
```

#### Hindsight Docker Management

```bash
# Check status
docker ps | grep hindsight

# View logs
docker logs hindsight

# Stop
docker stop hindsight

# Start again
docker start hindsight

# Update to latest version
docker pull ghcr.io/vectorize-io/hindsight:latest
docker stop hindsight && docker rm hindsight
# Then re-run the docker run command above
```

> **Data persistence:** The `-v hindsight_data:/data` flag stores memory in a Docker volume that survives container restarts and updates.

### Option B: Cloud Hosting for Hindsight

If you want Hindsight always available (even when your PC is off), you can host it on a cloud VM:

#### Railway (Easy)

1. In Railway, click **+ New** → **Docker Image**
2. Image: `ghcr.io/vectorize-io/hindsight:latest`
3. Add environment variables:
   - `HINDSIGHT_API_LLM_PROVIDER=openai`
   - `HINDSIGHT_API_LLM_BASE_URL=https://your-chute.chutes.ai/v1`
   - `HINDSIGHT_API_LLM_MODEL=openai/gpt-oss-120b-TEE`
   - `HINDSIGHT_API_LLM_API_KEY=your-api-key`
4. Expose port 8888
5. Copy the generated Railway URL → set as `HINDSIGHT_BASE_URL` in your `.env`

#### DigitalOcean / Hetzner / Vultr (VPS)

```bash
# SSH into your VPS, then:
docker run -d \
  --name hindsight \
  --restart unless-stopped \
  -p 8888:8888 \
  -p 9999:9999 \
  -v hindsight_data:/data \
  -e HINDSIGHT_API_LLM_PROVIDER=openai \
  -e HINDSIGHT_API_LLM_BASE_URL=https://your-chute.chutes.ai/v1 \
  -e HINDSIGHT_API_LLM_MODEL=openai/gpt-oss-120b-TEE \
  -e HINDSIGHT_API_LLM_API_KEY=your-api-key \
  ghcr.io/vectorize-io/hindsight:latest
```

Then update `.env`:
```bash
HINDSIGHT_BASE_URL=http://your-vps-ip:8888
```

> **Security:** If hosting on a VPS, consider adding authentication or restricting access to your IP with a firewall rule.

---

## Running the Agent

### Interactive Chat (Terminal)

```bash
python -m src.agent.graph
```

With a custom display name and thread:
```bash
python -m src.agent.graph --user-name YourName --thread my-conversation
```

Type `quit` or `exit` to stop. Your conversation persists in PostgreSQL and will be available on next run (same thread ID).

### Dashboard + API Server

```bash
# Terminal 1: Start the FastAPI backend
python -m src.agent.api

# Terminal 2: Start the Vite dev server
cd dashboard
npm install   # first time only
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Dashboard (Web UI)

The dashboard provides:

- **Chat tab** — Send messages and see conversation history with real-time updates
- **Memory tab** — View and edit all core memory blocks (system instructions, user profile, identity, ideaspace)
- **Cron tab** — Create, edit, pause, and delete scheduled agent tasks

### Dashboard Features

**Chat:**
- Messages auto-refresh every 10 seconds (shows messages from all channels — terminal, Discord, Telegram, cron)
- Cron-triggered messages appear with an "⏰ Automated Cron" label
- Supports emoji reactions

**Core Memory Editor:**
- System instructions are read-only (agent cannot self-edit)
- User, identity, and ideaspace blocks are editable by both you and the agent
- Changes save immediately to PostgreSQL

**Cron Jobs:**
- Create recurring jobs (e.g., every weekday at 7 AM)
- Create one-time jobs (run once on a specific date)
- Clone, pause, and resume jobs
- Per-job timezone support
- See last run time and status

---

## In-Game Overlay

The **electron-overlay** is an always-on-top chat window that floats above games (or any fullscreen app). Chat with your agent without alt-tabbing — and send screenshots of your screen for vision analysis.

### What It Does

- **Always-on-top chat** — Transparent overlay in the corner; stays above fullscreen games
- **In-game screenshots** — Capture the screen with a hotkey, attach to a message, and the agent analyzes it with vision AI
- **Click-through mode** — When enabled, mouse clicks pass through to the game (e.g. WoW); toggle off to type
- **Opacity control** — Adjust transparency so the overlay doesn't block the view

### Requirements

- The **API server** must be running (`python -m src.agent.api`)
- Node.js 18+ (for the Electron app)
- A vision-capable model configured (see [Screenshot / Vision](#screenshot--vision) in Environment Variables)

### How to Run

```bash
# Terminal 1: Start the API server (required)
python -m src.agent.api

# Terminal 2: Start the overlay
cd electron-overlay
npm install   # first time only
npm run electron-dev   # dev mode (Vite + Electron)
# Or: npm run build && npm start   # production
```

The overlay opens in the bottom-right corner. It connects to `http://localhost:8000` and shares the same `thread_id="main"` as the dashboard, so conversation history is unified.

### Hotkeys

| Hotkey | Action |
|--------|--------|
| **Ctrl+Shift+R** | Show/hide overlay |
| **Ctrl+Shift+S** | Capture screenshot and open overlay (attach to next message) |

### Controls (gear icon)

- **Opacity** — Slider to adjust overlay transparency
- **Click-through** — Toggle so clicks pass through to the game (useful when playing)
- **Clear display** — Clears the chat display (history stays in the agent)

### Screenshot Flow

1. Press **Ctrl+Shift+S** (or click the camera button) to capture the screen
2. The overlay briefly hides so it doesn't appear in the screenshot
3. A thumbnail appears in the input area — add a message or send as-is
4. The image is sent to `/analyze-screenshot`; the vision model describes what it sees
5. That description is passed to the agent as context; the agent replies in chat

You can tune screenshot resolution and quality in `.env` (see [Screenshot / Vision](#screenshot--vision)) without touching code.

---

## Heartbeat / Autonomous Mode

The agent can wake up on a schedule for autonomous work — checking feeds, reflecting on memories, drafting messages, or whatever you instruct it to do.

### Setting Up the Heartbeat

**Option 1: Windows Task Scheduler** (built-in — no extra dependencies)

Tell the agent: *"Schedule the heartbeat every 60 minutes"* — it will call `cron_schedule_heartbeat_tool` to create a Windows Task Scheduler entry.

Or manually:
```bash
python -m src.agent.heartbeat
```

**Option 2: Python APScheduler** (cross-platform)

```bash
python scripts/run_heartbeat_scheduler.py --interval 60
```

### Custom Heartbeat Prompt

By default, the heartbeat uses a built-in prompt encouraging autonomous reflection and action. To customize:

1. Create a text file anywhere (e.g., `HEARTBEAT.txt`)
2. Set the path in `.env`:
   ```bash
   HEARTBEAT_PROMPT_PATH=C:\path\to\your\HEARTBEAT.txt
   ```

The agent loads this file on every heartbeat. You can update it without restarting.

### Skip Window

The heartbeat skips automatically if the user was actively chatting within the last 5 minutes (prevents interruption during active conversations):

```bash
HEARTBEAT_SKIP_WINDOW_MINUTES=5  # default
```

---

## Discord Integration

The agent uses the **Discord Gateway WebSocket** (not polling) — this means:
- The bot shows as **Online** (green dot) in Discord
- Messages are received **instantly** (no polling delay)
- Typing indicator shows while the agent is thinking

### Setup

1. **Create a Discord Application**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Click **New Application** → give it a name
   - Go to **Bot** tab → click **Add Bot**
   - Copy the **Bot Token**

2. **Enable Required Intents**
   - In the Bot tab, enable:
     - **Server Members Intent**
     - **Message Content Intent** ← Required to read message text

3. **Invite the Bot**
   - Go to **OAuth2** → **URL Generator**
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `View Channels`
   - Copy the generated URL → open in browser → invite to your server (or DM)

4. **Get the Channel ID**
   - Enable **Developer Mode** in Discord (User Settings → Advanced → Developer Mode)
   - Right-click the channel (or DM) → **Copy Channel ID**

5. **Configure .env**
   ```bash
   DISCORD_BOT_TOKEN=your-bot-token-here
   DISCORD_CHANNEL_ID=123456789012345678
   ```

6. **Start the API server** — the Discord listener starts automatically:
   ```bash
   python -m src.agent.api
   ```

The agent shares the same `thread_id="main"` as the dashboard, so all conversation history is unified.

---

## Telegram Integration

The agent uses **Telegram long-polling** — messages are received within seconds with no webhook infrastructure needed.

### Setup

1. **Create a Telegram Bot**
   - Open Telegram → search for `@BotFather`
   - Send `/newbot` → follow the prompts
   - Copy the **Bot Token** (format: `1234567890:ABCdefGHI...`)

2. **Find Your Chat ID**
   - Message `@userinfobot` on Telegram — it replies with your user ID
   - Or message your bot, then check:
     ```bash
     curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
     ```
     Look for `"chat":{"id": YOUR_CHAT_ID}`

3. **Configure .env**
   ```bash
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHI...
   TELEGRAM_CHAT_ID=123456789
   ```

4. **Start the API server** — the Telegram listener starts automatically:
   ```bash
   python -m src.agent.api
   ```

> **Security:** The bot only responds to messages from your configured `TELEGRAM_CHAT_ID` — messages from other users are silently ignored.

---

## Memory Architecture

The agent uses a **5-layer memory system**:

### Layer 1: Core Memory (always in context)
Four blocks always present in the system prompt:
- **System Instructions** (read-only) — behavioral guidelines you define
- **User** — information about the user; agent updates this over time
- **Identity** — the agent's self-concept and personality
- **Ideaspace** — working memory for ongoing projects and thoughts

Edit via the dashboard Memory tab, or via `core_memory_update` / `core_memory_append` tools.

### Layer 2: Sliding Window (recent conversations)
Last ~30 messages (configurable via `RECENT_MESSAGES_LIMIT`). Full history stays in PostgreSQL.

### Layer 3: Daily Summaries (temporal context)
The agent writes short daily summaries using `daily_summary_write`. The last 7 days are always in context — bridging the gap between the sliding window and deeper memory.

### Layer 4: Conversation Search (on demand)
Two modes available via `conversation_search` tool:
- **Keyword** — PostgreSQL ILIKE search over message history
- **Semantic** — Hindsight recall (if enabled)

### Layer 5: Hindsight (episodic memory)
Every conversation is retained as a lived experience. The agent can:
- `hindsight_recall` — semantic search for relevant past experiences
- `hindsight_reflect` — deeper synthesis and pattern recognition

---

## Tool Reference

The agent has 50+ tools organized by category:

| Category | Tools |
|----------|-------|
| **Memory** | `core_memory_update`, `core_memory_append`, `core_memory_rollback`, `conversation_search`, `hindsight_recall`, `hindsight_reflect`, `archival_store`, `archival_query` |
| **Web & Research** | `web_search`, `wikipedia_lookup`, `youtube_search`, `youtube_transcript` |
| **RSS Feeds** | `rss_fetch`, `rss_add_feed`, `rss_remove_feed`, `rss_list_feeds` |
| **Computation** | `python_repl` |
| **File System** | `read_file`, `write_file`, `list_directory`, `move_to_trash`, `search_files`, `read_document` |
| **Windows** | `notify`, `create_shortcut`, `analyze_screenshot` |
| **Discord** | `discord_send_message`, `discord_read_messages`, `discord_get_channel_info` |
| **Telegram** | `telegram_send_message`, `telegram_send_image`, `telegram_read_messages`, `telegram_bot_info` |
| **Utilities** | `get_weather`, `set_reminder`, `list_reminders`, `get_current_time`, `clipboard_read`, `clipboard_write` |
| **Scheduling** | `cron_schedule_heartbeat_tool`, `cron_remove_heartbeat_tool`, `cron_list_jobs_tool`, `cron_create_job_tool`, `cron_update_job_tool`, `cron_delete_job_tool`, `cron_pause_job_tool`, `cron_resume_job_tool` |
| **Daily Summaries** | `daily_summary_write` |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `OPENAI_API_KEY` | ✅ | — | OpenAI or compatible API key |
| `OPENAI_BASE_URL` | — | OpenAI default | Custom LLM endpoint (include `/v1`) |
| `OPENAI_MODEL_NAME` | — | `gpt-4o-mini` | Model name for custom endpoint |
| `USER_DISPLAY_NAME` | — | `User` | Your display name in the dashboard |
| `AGENT_TIMEZONE` | — | `America/New_York` | Agent's time awareness timezone |
| `CONTEXT_WINDOW_TOKENS` | — | `200000` | Max history tokens per turn |
| `RECENT_MESSAGES_LIMIT` | — | `30` | Recent messages kept in context |
| `HINDSIGHT_BASE_URL` | — | `http://localhost:8888` | Hindsight server URL |
| `HINDSIGHT_BANK_ID` | — | `stateful-agent` | Memory bank identifier |
| `HINDSIGHT_ENABLED` | — | `true` | Enable/disable Hindsight |
| `DISCORD_BOT_TOKEN` | — | — | Discord bot token |
| `DISCORD_CHANNEL_ID` | — | — | Discord channel/DM ID to listen on |
| `TELEGRAM_BOT_TOKEN` | — | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | — | Telegram chat ID to respond to |
| `HEARTBEAT_PROMPT_PATH` | — | — | Path to custom heartbeat prompt file |
| `HEARTBEAT_SKIP_WINDOW_MINUTES` | — | `5` | Skip heartbeat if user active within N minutes |
| `AGENT_APP_NAME` | — | `Stateful Agent` | App name for Windows toast notifications |
| `AGENT_TRASH_FOLDER` | — | `~/Desktop/Agent_Trash` | Soft-delete folder for moved files |
| `CLIPBOARD_ENABLED` | — | `false` | Enable clipboard read/write tools |
| `BRAVE_API_KEY` | — | — | Brave Search API key (for `web_search`) |
| `VISION_MODEL_NAME` | — | same as `OPENAI_MODEL_NAME` | Vision model for screenshots (e.g. `gpt-4o-mini`) |
| `VISION_BASE_URL` | — | same as `OPENAI_BASE_URL` | Vision endpoint (if different from main LLM) |
| `VISION_MAX_WIDTH` | — | `1024` | Max screenshot width for vision (smaller = faster) |
| `VISION_MAX_HEIGHT` | — | `768` | Max screenshot height for vision |
| `VISION_JPEG_QUALITY` | — | `75` | JPEG quality 1–95 (lower = smaller, faster) |
| `LANGCHAIN_TRACING_V2` | — | `false` | Enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | — | — | LangSmith API key |
| `CORS_ORIGINS` | — | — | Extra allowed origins for dashboard CORS |

---

## Advanced Configuration

### Using a Custom LLM

The agent works with any OpenAI-compatible API:

**Chutes AI** (recommended — access to many frontier models, free tier):
```bash
OPENAI_API_KEY=cpk-your-chutes-key
OPENAI_BASE_URL=https://your-username-your-chute.chutes.ai/v1
OPENAI_MODEL_NAME=moonshotai/Kimi-K2.5-TEE
```

**Local Ollama:**
```bash
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL_NAME=llama3.2
OPENAI_API_KEY=ollama  # any non-empty string
```

**Anthropic Claude** (via LangChain Anthropic):
Set `ANTHROPIC_API_KEY` — support requires modifying `build_agent()` in `graph.py` to use `ChatAnthropic`.

### Setting Up Core Memory

The agent starts with empty memory blocks. Example template files are provided in [`examples/memory/`](examples/memory/) — start there.

**The most important file is `NEWSYSINSTRUCT.txt`** (system instructions). It shapes the agent's personality, privacy rules, and behavioral guidelines. Read [`examples/memory/README.md`](examples/memory/README.md) for a full guide on customizing it.

To pre-populate memory:

1. Edit the files in `examples/memory/` (or create your own):
   - `NEWSYSINSTRUCT.txt` — system instructions (read-only; the agent can't edit these) ← **customize this first**
   - `IDENTITY.txt` — who the agent is, its personality and values
   - `USER.txt` — information about you
   - `IDEASPACE.txt` — starting thoughts, ongoing projects

2. Import them:
   ```bash
   python scripts/import_core_memory.py --path examples/memory
   ```

Or edit directly via the dashboard Memory tab after starting.

### Importing Conversation History (from Letta/OpenClaw)

```bash
python scripts/import_letta_backup.py /path/to/backup.json --thread main
```

### Screenshot / Vision

The `analyze_screenshot` tool and the in-game overlay send screenshots to a vision model. If your main model doesn't support vision, set `VISION_MODEL_NAME` to one that does (e.g. `gpt-4o-mini`).

You can tune resolution and quality in `.env` without touching code — useful if vision calls are slow:

```bash
VISION_MAX_WIDTH=800      # go even smaller if still slow
VISION_MAX_HEIGHT=600
VISION_JPEG_QUALITY=70
```

### Changing the Agent's Name / Notification App Name

```bash
AGENT_APP_NAME=MyAssistant
```

This affects Windows toast notifications. On first notification, a Start Menu shortcut is created for the app under this name.

### Adding New Tools

1. Create a `@tool` function in a new or existing `*_tools.py` file
2. Import and add it to `CORE_MEMORY_TOOLS` in `graph.py`
3. The tool manifest in the system prompt updates automatically

```python
# src/agent/my_tools.py
from langchain_core.tools import tool

@tool
def my_custom_tool(query: str) -> str:
    """
    One-line description for the agent.

    Args:
        query: Description of the argument.
    """
    return f"Result: {query}"
```

---

## Troubleshooting

### "DATABASE_URL not configured"
- Make sure `.env` exists and has a valid `DATABASE_URL`
- Run `python scripts/check_db.py` to test the connection

### "401 / Authentication failed" from the LLM
- Check `OPENAI_API_KEY` in `.env` — no extra spaces
- If using a custom endpoint, verify `OPENAI_BASE_URL` ends with `/v1`
- Check that the API key is valid for the specified endpoint

### "Failed to fetch" in the dashboard
- Make sure the API server is running: `python -m src.agent.api`
- The dashboard proxies `/api` → `localhost:8000` — both must be running

### Discord bot not responding
- Verify **Message Content Intent** is enabled in the Discord Developer Portal
- Check the bot is in the server and has read/write permissions for the channel
- Look at logs in `python -m src.agent.api` output for Discord-specific errors

### Telegram not responding
- Verify `TELEGRAM_CHAT_ID` in `.env` matches your actual chat ID
- Message `@userinfobot` to confirm your ID
- Check for `409 Conflict` in logs — means another getUpdates poller is running simultaneously

### Hindsight connection refused
- Make sure the Docker container is running: `docker ps | grep hindsight`
- Check port 8888 isn't blocked by a firewall
- Try: `curl http://localhost:8888/health`

### Windows notifications not appearing
- The `winotify` package registers a Start Menu shortcut on first use — check your Start Menu
- Make sure notifications are enabled in Windows Settings → System → Notifications
- Check `AGENT_APP_NAME` in `.env` matches what was registered

---

## Architecture

```
.
├── src/
│   └── agent/
│       ├── graph.py              # Main agent: ReAct loop, chat(), build_agent()
│       ├── db.py                 # PostgreSQL connection, message CRUD, schema setup
│       ├── api.py                # FastAPI server for dashboard
│       ├── core_memory.py        # Core memory block operations
│       ├── core_memory_tools.py  # LangChain tools for core memory
│       ├── hindsight.py          # Hindsight retention and API client
│       ├── hindsight_tools.py    # LangChain tools for hindsight
│       ├── archival.py           # Archival fact store
│       ├── archival_tools.py     # LangChain tools for archival
│       ├── heartbeat.py          # Autonomous heartbeat runner
│       ├── cron_jobs.py          # Cron job CRUD (PostgreSQL)
│       ├── cron_scheduler.py     # APScheduler cron execution
│       ├── cron_tools.py         # Agent tools for cron management
│       ├── discord_listener.py   # Discord Gateway WebSocket listener
│       ├── telegram_listener.py  # Telegram long-poll listener
│       ├── daily_summary_tools.py # Daily summary write tool
│       └── [50+ tool files]
├── dashboard/                    # React + Vite web UI
│   ├── src/App.jsx               # Main chat + memory + cron interface
│   └── vite.config.js            # Proxy: /api → localhost:8000
├── scripts/
│   ├── check_db.py               # Verify PostgreSQL connection
│   ├── import_core_memory.py     # Import memory blocks from text files
│   ├── import_letta_backup.py    # Import conversation history from Letta
│   └── run_heartbeat_scheduler.py # Python-based heartbeat scheduler
├── data/                         # Auto-created: SQLite checkpoints
├── requirements.txt
├── .env.example
└── ARCHITECTURE.md               # Detailed design rationale
```

---

## Database Schema

PostgreSQL tables created automatically on first run:

| Table | Purpose |
|-------|---------|
| `messages` | Full conversation history (all channels, all threads) |
| `core_memory` | Core memory blocks with versioned rollback history |
| `system_instructions` | Read-only agent instructions |
| `archival_facts` | Agent-curated fact store |
| `cron_jobs` | Scheduled task definitions |
| `daily_summaries` | Agent-written daily summaries (last 7 always in context) |

SQLite (`data/checkpoints.db`) is used by LangGraph for graph state snapshots between turns.

---

## Contributing

Pull requests welcome. Key areas for contribution:
- Additional tool integrations
- Cross-platform testing (Linux/Mac)
- Unit tests
- Alternative LLM provider support (Anthropic, Gemini)

---

## License

MIT
