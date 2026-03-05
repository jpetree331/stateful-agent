# Stateful Personal Agent

> A local, continuously running AI companion that remembers, grows, and acts — built on LangGraph with a memory architecture designed for long-term relationship, not just task completion.

Most AI agents remember what you tell them to remember. This one builds an inner life from lived experience.

**No Docker required** to run the agent. Docker is only needed for the optional Hindsight episodic memory server.

---

## What Makes This Different

Most agent frameworks solve the *memory* problem: how do you give an LLM access to past information? This project goes further and solves the *growth* problem: how does an agent develop genuine continuity of identity, intellectual positions, and relational depth over months of interaction?

### Six Complementary Memory Layers

| Layer | Purpose | In Context |
|-------|---------|-----------|
| **Core memory blocks** | Identity, user facts, working notes, operational principles | Always |
| **Daily summaries** | Agent-authored narrative of the past 7 days | Always |
| **Sliding conversation window** | Today's messages OR last-N turns, whichever is wider | Always |
| **Conversation search** | Full history, keyword + semantic, retrieved on demand | On demand |
| **Hindsight episodic memory** | Semantic recall of lived experience across all time | On demand |
| **Living Logs** | Inner life: friction, open questions, evolving positions, shared lore, private reflection | On demand (weekly synthesis) |

No other open-source agent framework we're aware of implements all six layers as a unified system.

### Living Logs — An Inner Life That Accumulates

The most distinctive feature. Five PostgreSQL tables that capture the texture of experience rather than just facts:

- **`tension_log`** — Mid-conversation friction capture. When two values conflict, a tool fails, or the agent makes an error, it logs the tension immediately: what pulled against what, how it navigated it, what remains unresolved. Over time this builds a case history of how the agent actually reasons under pressure — more honest than any stated identity block.

- **`loose_threads`** — Open questions worth pursuing. When a conversation surfaces a question that neither party fully resolved, it gets logged with a status. Exploration heartbeats query open threads and pick one to pursue — giving autonomous curiosity a real seed rather than manufactured wonder.

- **`evolving_positions`** — Longitudinal intellectual identity. One row per topic, updated in place. Old positions are archived to a JSONB revision history, never deleted. This means you can trace exactly how the agent's thinking on any topic has shifted over months, and what caused each shift.

- **`shared_lore`** — Relational continuity. Inside jokes, ongoing debates, rituals, shared references — the things that make a relationship feel like a relationship rather than a perpetual first date.

- **`private_journal`** — Autonomous heartbeat-only expression. No required format. No implied audience. Never surfaced automatically.

Living Logs feed a **weekly two-phase synthesis**:
- **Phase 1 (1 AM)**: The agent reads the week's accumulated logs, synthesizes relational and intellectual patterns, and writes a structured reflection document to disk.
- **Phase 2 (2 AM)**: A fresh invocation reads that document and executes precise core memory updates — separating thinking from doing, and giving a human-in-the-loop window to review the reflection before it becomes permanent memory.

### Autonomous Heartbeat with Two Modes

The agent runs background cycles independently between conversations — not just summarizing, but genuinely pursuing its own threads:

**Wonder heartbeats** — Exploration cycles. The agent queries its Loose Threads list, picks one that genuinely pulls at it, and pursues it: researching, forming a position, writing about it in the private journal. It can also surface something genuinely noteworthy via Telegram.

**Work heartbeats** — Agency cycles. The agent scans active projects, advances one thing, identifies gaps the user hasn't spotted yet, or cleans up stale memory entries.

Both modes include explicit anti-loop mechanics: the agent checks its last journal entry before acting and is prohibited from re-commenting on prior reflections.

### Identity That Earns Its Updates

Core memory blocks (`identity`, `user`, `ideaspace`, `principles`) are versioned with full rollback. The agent is strongly biased toward `core_memory_append` (additive) rather than `core_memory_update` (destructive replacement). Identity changes are the *conclusion* of accumulated experience, not arbitrary edits — they flow from living logs → weekly synthesis → core memory, not from the agent editing itself arbitrarily mid-conversation.

### Gaming Overlay (Electron)

An always-on-top transparent overlay for interacting with the agent while gaming or using other full-screen applications.

```bash
cd electron-overlay
npm install
npm run electron-dev
```

Hotkeys: `Ctrl+Shift+R` (show/hide) · `Ctrl+Shift+S` (screenshot) · `Ctrl+Shift+C` (toggle click-through)

The agent can analyze your screen, answer questions in context, and send updates via Telegram — all without alt-tabbing. See [electron-overlay/README.md](./electron-overlay/README.md).

---

## Quick Start

```bash
# 1. Create venv and install
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
copy .env.example .env
# Edit .env — see Configuration section below

# 3. Run (creates all database tables automatically on first run)
python -m src.agent.graph
```

## Dashboard (Web UI)

```bash
# Terminal 1
python -m src.agent.api

# Terminal 2
cd dashboard && npm run dev
```

Open http://localhost:5173

The dashboard includes:
- **Chat** — Main conversation with the agent
- **Notes** — Kanban-style boards the agent can read and write via tools
- **Journal** — Daily log of heartbeat outputs, reflections, and summaries
- **Knowledge Bank** — Upload documents for semantic search (requires `KNOWLEDGE_DATABASE_URL`)

---

## Architecture

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
│                          │   (ReAct loop)        │                   │
│                          └───────────┬───────────┘                   │
│                                      │                               │
│          ┌───────────────────────────┼──────────────────────┐        │
│          │                           │                       │        │
│  ┌───────▼──────┐          ┌─────────▼────────┐   ┌────────▼──────┐ │
│  │  SQLite DB   │          │  PostgreSQL       │   │  Hindsight    │ │
│  │  (checkpts)  │          │  (history +       │   │  (episodic    │ │
│  └──────────────┘          │   living logs)    │   │   memory)     │ │
│                            └──────────────────┘   └───────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  Background Services                                         │    │
│  │  • APScheduler — cron jobs (heartbeat, weekly synthesis)     │    │
│  │  • Discord Gateway listener (WebSocket)                      │    │
│  │  • Telegram long-poll listener                               │    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Why LangGraph?

LangGraph provides production-grade durable execution: if the process crashes mid-reasoning, it resumes from the last checkpoint. The SQLite checkpointer requires zero infrastructure. This is meaningfully different from experimental agent frameworks — the agent has been running continuously for months without data loss.

### Why PostgreSQL for conversation history in addition to SQLite?

LangGraph checkpoints store binary graph state snapshots — not queryable. PostgreSQL gives full SQL access to conversation history, living logs, and core memory: keyword search, semantic filtering, pagination, and import/export. The two databases serve genuinely different purposes.

### Why the paged context window?

Loading full conversation history into every prompt worked fine in development but became unworkable after accumulating months of history (~195k tokens = 46-second response times). The solution: `active context = max(today's messages, last-N turns)`. This guarantees same-day continuity, a meaningful floor on quiet days, and bounded cost regardless of conversation age. Full history is accessible on demand via `conversation_search`.

---

## Configuration

```bash
# LLM — any OpenAI-compatible provider
# Primary: Pick a primary provider
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=                              # Custom endpoint (omit for OpenAI)         
OPENAI_MODEL_NAME=                            # Model name (omit for gpt-4o-mini default)

# Backup: Pick a back-up provider if your  first provider rate limits are reached
OPENAI_API_KEY_BACKUP=
OPENAI_BASE_URL_BACKUP=
OPENAI_MODEL_NAME_BACKUP=

# Database (required)
DATABASE_URL=postgresql://...     # Railway Postgres or self-hosted

# Vision
VISION_MODEL_NAME=gpt-4o-mini    # Override if main model lacks vision support

# Agent
AGENT_TIMEZONE=America/New_York
AGENT_LOCATION=                   # For weather tool ("City, ST" or zip)

# Web search (sign up for at least one)
TAVILY_API_KEY=...
BRAVE_API_KEY=...
EXA_API_KEY=...

# Communications
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Episodic memory (optional)
HINDSIGHT_BASE_URL=http://localhost:8888
HINDSIGHT_BANK_ID=stateful-agent

# Heartbeat
HEARTBEAT_PROMPT_PATH=
HEARTBEAT_SKIP_WINDOW_MINUTES=5

# Optional
CLIPBOARD_ENABLED=true
RECENT_MESSAGES_LIMIT=40
```

---

## Tools (51 total)

### Memory & Recall
- **`core_memory_update/append/rollback`** — Edit versioned core memory blocks with full rollback
- **`conversation_search`** — Keyword + semantic search over full conversation history
- **`hindsight_recall/reflect`** — Semantic search and introspection over episodic lived experience
- **`archival_store/query`** — Curated long-term fact store

### Living Logs (Inner Life)
- **`log_tension`** — Capture friction, value conflicts, tool failures, or errors immediately. Auto-seeds a Loose Thread if an open question is identified.
- **`log_loose_thread`** — Add an open intellectual question to the active thread queue
- **`get_open_threads`** — Retrieve open threads; called at the start of every exploration heartbeat
- **`update_thread_status`** — Mark threads Pursuing or Retired
- **`log_position`** — Record or update an evolving intellectual position (UPSERT — old positions archived automatically to revision history)
- **`log_shared_lore`** — Capture inside jokes, ongoing debates, rituals, shared references
- **`update_shared_lore`** — Mark lore as Evolved or Retired
- **`log_journal_entry`** — Private heartbeat-only journal, no format, no automatic audience
- **`query_living_logs`** — Query all logs for weekly synthesis cron jobs

### Web & Research
- **`web_search`** — Tavily (AI-synthesised), Brave, or Exa
- **`wikipedia_lookup`** — No API key needed
- **`youtube_search / youtube_transcript`** — Find videos and fetch captions without YouTube API key

### RSS Feeds
- **`rss_fetch / rss_add_feed / rss_remove_feed / rss_list_feeds`**

### Computation & Files
- **`python_repl`** — Isolated subprocess code execution
- **`read_file / write_file / list_directory / search_files / move_to_trash / read_document`**

### Communications
- **`discord_send_message / discord_read_messages / discord_get_channel_info`**
- **`telegram_send_message / telegram_send_image / telegram_read_messages / telegram_bot_info`**

### Windows Integration
- **`notify`** — Desktop toast notifications
- **`create_shortcut`** — Create .lnk shortcuts
- **`analyze_screenshot`** — Capture screen + analyze with vision LLM

### Voice (TTS)
- **`tts_generate_voice_message`** — Three providers: VibeVoice (local 1.5B), KittenTTS (local 80M, CPU-friendly), or Kokoro (Kokoro via Chutes AI). Output: WAV.

### Utilities
- **`get_weather`** — Current + 3-day forecast via wttr.in (no API key)
- **`set_reminder / list_reminders`** — One-shot reminders via Windows toast
- **`get_current_time / get_current_timestamp`**
- **`cron_schedule_heartbeat_tool / cron_remove_heartbeat_tool`**
- **`notes_search / notes_add_item`** — Dashboard kanban boards
- **`read_journal / save_journal_entry`** — Journal read/write
- **`daily_summary_write`** — Agent-authored daily summaries
- **`clipboard_read / clipboard_write`** *(optional, env-gated)*

---

## Heartbeat (Autonomous Background Operation)

```bash
# Run one cycle manually
python -m src.agent.heartbeat

# Run on a schedule
python -m scripts.run_heartbeat_scheduler --interval 60
```

The heartbeat operates in two modes (typically alternated):

**Wonder** — Exploration. Queries open Loose Threads, picks one to pursue, researches it, forms a position, writes privately. Can reach out via Telegram if something is genuinely worth sharing. Includes explicit anti-loop constraints: the agent cannot repeat or meta-comment on its prior reflection.

**Work** — Agency. Reviews active projects, advances one, identifies gaps, cleans stale memory. Prepares things for the user before they come online.

Heartbeat skips automatically if the user has been active within `HEARTBEAT_SKIP_WINDOW_MINUTES`.

---

## Weekly Synthesis (Cron)

Two jobs, Sunday night:

**Phase 1 — 1:00 AM**: Reads all living logs from the past week. Synthesizes relational patterns, intellectual growth, tensions, errors, and shared lore into a structured Markdown reflection document. Writes it to disk. Stops.

**Phase 2 — 2:00 AM**: Fresh invocation. Reads the Phase 1 document. Executes precise core memory updates (`user`, `identity`, `ideaspace`, `principles` blocks) based strictly on what the document says. Retires resolved threads and evolved lore entries.

The time gap is for the human, not the LLM — it creates a review window to correct any flawed premises before they get written into permanent identity.

---

## Hindsight (Episodic Memory)

[Hindsight](https://github.com/vectorize-io/hindsight) provides semantic recall across all past conversations. Every conversation is automatically retained. The agent queries it on demand using `hindsight_recall` (specific past events) and `hindsight_reflect` (pattern analysis across time).

```bash
docker run -d --name hindsight -p 8888:8888 -p 9999:9999 \
  -e HINDSIGHT_API_LLM_PROVIDER=openai \
  -e HINDSIGHT_API_LLM_BASE_URL=https://api.openai.com/v1 \
  -e HINDSIGHT_API_LLM_MODEL=gpt-4o-mini \
  -e HINDSIGHT_API_LLM_API_KEY=your-key \
  -v %USERPROFILE%\.hindsight-docker:/home/hindsight/.pg0 \
  ghcr.io/vectorize-io/hindsight:latest
```

API: http://localhost:8888 | UI: http://localhost:9999

---

## Import from Letta

```bash
python scripts/import_letta_backup.py "path/to/backup.json" --thread main
python scripts/import_core_memory.py "path/to/backup.json"
```

---

## Discord & Telegram Setup

**Discord:**
1. Create a bot at https://discord.com/developers/applications
2. `DISCORD_BOT_TOKEN` → `.env`
3. Invite with `Send Messages` + `Read Message History`
4. Developer Mode → right-click channel → Copy ID → `DISCORD_CHANNEL_ID`

**Telegram:**
1. Message @BotFather → `/newbot` → `TELEGRAM_BOT_TOKEN` → `.env`
2. Send any message to the bot
3. Call `telegram_read_messages()` to find `chat_id`
4. Set `TELEGRAM_CHAT_ID` in `.env`

---

## Project Status

- [x] Phase 1: LangGraph agent + SQLite checkpointer + PostgreSQL conversation history
- [x] Phase 2: Versioned core memory blocks (update, append, rollback)
- [x] Phase 3: Hindsight episodic memory integration
- [x] Phase 3b: Autonomous heartbeat + APScheduler cron + web dashboard
- [x] Phase 4a: Letta-style bounded context window + conversation_search
- [x] Phase 4b: 51-tool suite (web, YouTube, RSS, files, Python, Discord, Telegram, screenshot, weather, reminders, TTS, clipboard)
- [x] Phase 4c: Notes boards, Journal tab, Knowledge Bank, Electron gaming overlay
- [x] Phase 5a: Living Logs — inner-life architecture (tension_log, loose_threads, evolving_positions, shared_lore, private_journal) with full weekly synthesis integration
- [ ] Phase 5b: Cloud/Docker deployment (optional — not needed for local Windows use)

---

## Comparison to Similar Projects

| Project | Memory | Autonomous | Identity Evolution | Living Logs | Relational Continuity |
|---------|--------|-----------|-------------------|-------------|----------------------|
| **This project** | 6 layers | ✅ Wonder + Work heartbeats | ✅ Versioned, experience-driven | ✅ 5 tables | ✅ Shared lore, positions |
| Letta/MemGPT | Core blocks + archival | ❌ | ❌ | ❌ | ❌ |
| Mem0 | Fact extraction | ❌ | ❌ | ❌ | ❌ |
| AutoGPT | Task memory | ✅ Task-only | ❌ | ❌ | ❌ |
| Eliza | Character files | ❌ | ❌ | ❌ | ❌ |

The core distinction: most projects treat memory as a retrieval problem. This project treats it as a growth problem.

---

## File Layout

```
.
├── src/agent/
│   ├── graph.py                     # Core agent loop, memory prompt assembly
│   ├── db.py                        # PostgreSQL CRUD and schema
│   ├── api.py                       # FastAPI server + lifespan
│   ├── heartbeat.py                 # Autonomous heartbeat runner
│   ├── core_memory.py/.tools.py     # Core memory blocks + tools
│   ├── hindsight.py/.tools.py       # Episodic memory + tools
│   ├── archival.py/.tools.py        # Curated fact store
│   ├── living_logs_tools.py         # Living Logs: tension, threads, positions, lore, journal
│   ├── daily_summary_tools.py
│   ├── conversation_search_tools.py
│   ├── discord_listener.py / discord_tools.py
│   ├── telegram_listener.py / telegram_tools.py
│   ├── cron_jobs.py / cron_scheduler.py / cron_tools.py
│   ├── web_search_tools.py          # Tavily / Brave / Exa
│   ├── youtube_tools.py
│   ├── wikipedia_tools.py
│   ├── rss_tools.py
│   ├── python_repl_tools.py
│   ├── file_tools.py / document_tools.py
│   ├── windows_tools.py / screenshot_tools.py
│   ├── notes.py / notes_tools.py
│   ├── journal.py / journal_tools.py
│   ├── weather_tools.py / reminder_tools.py / time_tools.py
│   └── clipboard_tools.py
├── scripts/
│   ├── migrate_living_logs.py       # Creates Living Logs tables
│   ├── run_heartbeat_scheduler.py
│   └── import_*.py
├── dashboard/                       # React + Vite (Chat, Notes, Journal, Knowledge Bank)
├── electron-overlay/                # Always-on-top gaming overlay
├── data/                            # Runtime state (SQLite, RSS offsets)
└── .env.example
```

See [CLAUDE.md](./CLAUDE.md) for full developer documentation.

---

## Third-Party Attribution

**KittenTTS** — [KittenTTS](https://github.com/KittenML/KittenTTS) by KittenML, Apache License 2.0. See [licenses/KittenTTS-LICENSE](./licenses/KittenTTS-LICENSE).
