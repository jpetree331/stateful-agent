# AGENTS.md — AI Coding Agent Guide

This file contains essential information for AI coding agents working on the **Stateful Agent** project. This is a local, stateful agent built with LangGraph that runs on your PC, remembers itself across sessions, and has agency through tools.

---

## Project Overview

This project implements a stable alternative to Letta/OpenClaw using LangGraph's production-ready persistence and memory systems. The agent uses a **dual-database architecture**:

- **SQLite** (`data/checkpoints.db`): LangGraph checkpointer for graph state snapshots
- **PostgreSQL** (Railway): Long-term storage for conversation history, core memory, and archival facts

### Key Features

- **ReAct Agent**: LLM with tool-calling capabilities
- **Core Memory**: Four editable memory blocks always in context (user, identity, ideaspace, system_instructions)
- **Hindsight Integration**: Deep memory with recall and reflection capabilities
- **Heartbeat System**: Autonomous wake-up cycles for background thinking
- **Web Dashboard**: React + Vite frontend for chat interface

---

## Technology Stack

### Backend (Python)

| Component | Technology |
|-----------|------------|
| Framework | LangGraph >= 1.0 |
| LLM Integration | LangChain + OpenAI/Anthropic |
| State Persistence | SQLite (checkpoints) |
| Conversation History | PostgreSQL (Psycopg 3) |
| Deep Memory | Hindsight Client |
| Scheduling | APScheduler (Python) / Windows Task Scheduler |
| API Server | FastAPI + Uvicorn |

### Frontend (Dashboard)

| Component | Technology |
|-----------|------------|
| Framework | React 19 |
| Build Tool | Vite 7 |
| Styling | Tailwind CSS 4 |
| Markdown | react-markdown |

---

## Project Structure

```
.
├── src/agent/                    # Main agent code
│   ├── graph.py                  # ReAct agent, chat(), run_local()
│   ├── db.py                     # PostgreSQL connection, message CRUD
│   ├── api.py                    # FastAPI server for dashboard
│   ├── core_memory.py            # Core memory block operations
│   ├── core_memory_tools.py      # LangChain tools for core memory
│   ├── hindsight.py              # Hindsight retention and API client
│   ├── hindsight_tools.py        # LangChain tools for Hindsight
│   ├── archival.py               # Archival memory operations
│   ├── archival_tools.py         # LangChain tools for archival
│   ├── cron_tools.py             # Windows Task Scheduler integration
│   └── heartbeat.py              # Autonomous heartbeat runner
├── scripts/                      # Utility scripts
│   ├── import_letta_backup.py    # Import Letta conversation history
│   ├── import_core_memory.py     # Import core memory from text files
│   ├── check_db.py               # Verify database connection
│   └── run_heartbeat_scheduler.py # Python-based heartbeat scheduler
├── dashboard/                    # React + Vite web UI
│   ├── src/App.jsx               # Main chat interface
│   ├── package.json              # Node dependencies
│   └── vite.config.js            # Vite config with proxy
├── data/                         # SQLite checkpoints (gitignored)
├── .env                          # Environment configuration
├── requirements.txt              # Python dependencies
└── ARCHITECTURE.md               # Detailed design rationale
```

---

## Setup and Installation

### Prerequisites

- Python 3.12+
- PostgreSQL database (Railway recommended)
- Node.js 20+ (for dashboard)

### Initial Setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install Python dependencies
pip install -r requirements.txt

# Copy and configure environment
opy .env.example .env
# Edit .env with your DATABASE_URL and OPENAI_API_KEY
```

### Environment Variables

Critical variables in `.env`:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (Railway) |
| `OPENAI_API_KEY` | LLM API key (or Chutes API key) |
| `OPENAI_BASE_URL` | Custom LLM endpoint (optional) |
| `OPENAI_MODEL_NAME` | Model name for custom endpoints |
| `CONTEXT_WINDOW_TOKENS` | Max tokens for history (default: 200000) |
| `HINDSIGHT_BASE_URL` | Hindsight server URL |
| `HINDSIGHT_BANK_ID` | Hindsight memory bank identifier |
| `HEARTBEAT_PROMPT_PATH` | Path to HEARTBEAT.txt (optional) |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing |

---

## Running the Application

### Interactive Chat (CLI)

```bash
# Start interactive chat
python -m src.agent.graph

# With custom user label and thread
python -m src.agent.graph --user-name YourName --thread my-conversation
```

### Dashboard (Web UI)

Terminal 1: Start backend
```bash
python -m src.agent.api
```

Terminal 2: Start frontend
```bash
cd dashboard
npm install  # First time only
npm run dev
```

Open http://localhost:5173

### Heartbeat (Autonomous Mode)

```bash
# Single heartbeat cycle
python -m src.agent.heartbeat

# Continuous scheduler (Python)
python -m scripts.run_heartbeat_scheduler --interval 60

# Or schedule via Windows Task Scheduler (agent tool)
```

---

## Development Commands

### Database Operations

```bash
# Check database connection
python scripts/check_db.py

# Import Letta backup
python scripts/import_letta_backup.py "path/to/backup.json" --thread main

# Import core memory from text files
python scripts/import_core_memory.py --path "C:\path\to\memory\files"
```

### Dashboard Development

```bash
cd dashboard
npm run dev       # Development server
npm run build     # Production build
npm run lint      # ESLint
npm run preview   # Preview production build
```

---

## Code Organization and Patterns

### Agent Architecture

1. **StateGraph**: ReAct agent with LLM node → tool node → LLM loop
2. **Checkpointer**: SQLite for durable execution and restarts
3. **Memory Systems**:
   - **Core Memory**: Always in context, versioned with rollback
   - **Archival Memory**: Curated facts separate from conversation
   - **Hindsight**: External episodic memory with semantic search

### Adding New Tools

1. Define tool function in appropriate `*_tools.py` file
2. Decorate with `@tool` from `langchain_core.tools`
3. Add comprehensive docstring (agent uses this to understand purpose)
4. Import and add to `CORE_MEMORY_TOOLS` list in `graph.py`
5. Update system prompt instructions if needed

### Message Flow

1. User sends message via `chat()` in `graph.py`
2. System loads conversation history from Postgres with token sliding window
3. Checkpoint is cleared to avoid merge conflicts
4. ReAct agent invokes with `[SystemMessage] + history + [new_user_msg]`
5. Agent can call tools during execution
6. Messages persisted to Postgres, exchange retained to Hindsight

### Core Memory System

Four blocks always loaded into context:

1. **System Instructions** (read-only): Agent cannot edit
2. **User** (editable): Information about the user
3. **Identity** (editable): Agent's identity and personality
4. **Ideaspace** (editable): Working memory for ongoing thoughts

**Editing principles**:
- Prefer `core_memory_append` over `core_memory_update` to preserve content
- Use `core_memory_rollback` immediately if a mistake is made
- Each block maintains version history for one-step rollback

---

## Testing Strategy

- No formal test suite yet (Phase 4 roadmap item)
- Manual testing via `python -m src.agent.graph --thread test`
- Database schema auto-creates on first run via `setup_schema()`
- Enable LangSmith tracing for detailed execution traces

---

## Security Considerations

### Environment Variables

- `.env` file is gitignored — never commit API keys
- Use `.env.example` as template with placeholder values
- All secrets loaded via `python-dotenv` with `override=True`

### Database

- PostgreSQL connection string contains credentials — keep secure
- SQLite checkpointer is local file-based
- No input sanitization needed for LLM messages (trust boundary)

### Tool Safety

- Core memory tools warn against accidental deletion
- Rollback capability available for all core memory edits
- Windows Task Scheduler integration requires appropriate permissions

---

## Common Issues and Debugging

### 401 Authentication Errors

Check `.env` configuration:
- `OPENAI_API_KEY`: Use your Chutes API key (format: `cpk_...`)
- `OPENAI_BASE_URL`: Include `/v1` for OpenAI-compatible APIs
- `OPENAI_MODEL_NAME`: e.g., `moonshotai/Kimi-K2.5-TEE`

### Database Connection Failures

- Verify `DATABASE_URL` format: `postgresql://postgres:PASSWORD@HOST:PORT/railway`
- Run `python scripts/check_db.py` to verify connectivity
- Schema auto-creates on first agent run

### Hindsight Unavailable

- Check if Docker container is running: `docker ps`
- Verify `HINDSIGHT_BASE_URL` in `.env`
- Hindsight features gracefully degrade if unavailable

---

## Roadmap

- [x] Phase 1: Agent + SQLite checkpointer + Postgres conversation history
- [x] Phase 2: Core memory tools (update, append, rollback)
- [x] Phase 3: Hindsight integration (retain, recall, reflect)
- [x] Phase 3b: Heartbeat + cron scheduler
- [ ] Phase 4: Additional tools (bash, file system)
- [ ] Phase 5: Docker deployment

---

## References

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Detailed design rationale
- [README.md](./README.md) — User-facing quick start
- [CLAUDE.md](./CLAUDE.md) — Claude Code specific guidance
- [LangGraph Docs](https://docs.langchain.com/oss/python/langgraph/)
- [Hindsight](https://github.com/vectorize-io/hindsight) — Deep memory system
