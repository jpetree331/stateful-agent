# Stateful Agent Architecture — LangGraph

This document outlines the architecture for a **local, stateful agent** built with LangGraph. The goal is a stable alternative to Letta that runs on your PC, remembers itself across platforms, and has agency (tools) like OpenClaw.

---

## 1. Why LangGraph?

| Concern | LangGraph Approach |
|--------|--------------------|
| **Statefulness** | Built-in persistence via checkpointers (SQLite, Postgres). State survives restarts. |
| **Memory** | Short-term (thread-scoped) + long-term (Store) with semantic/episodic/procedural types. |
| **Durability** | Durable execution: resumes from last checkpoint after failures. |
| **Agency** | ReAct-style agents with tools. Prebuilt `create_react_agent` for quick setup. |
| **Stability** | Mature, production-focused (Klarna, Replit, Elastic). MIT license. |

---

## 2. Core Concepts

### 2.1 StateGraph

- **Nodes**: Functions that receive state and return updates.
- **Edges**: Connect nodes (or conditional routing).
- **State**: TypedDict with channels (e.g. `messages`, `llm_calls`).
- **Reducers**: How updates merge (e.g. `operator.add` for appending messages).

### 2.2 Persistence (Checkpointing)

- **Thread**: Unique ID (`thread_id`) for a conversation/session.
- **Checkpoint**: Snapshot of state at each step.
- **Checkpointer**: Where checkpoints are stored.

For local use:

- **SQLite** (`langgraph-checkpoint-sqlite`): Single file, no server. Good for local/dev.
- **Postgres** (`langgraph-checkpoint-postgres`): For Docker/production.

### 2.3 Memory Types

| Type | Scope | Use |
|------|--------|-----|
| **Short-term** | Thread | Conversation history, in-state. Persisted via checkpointer. |
| **Long-term** | Namespace (e.g. user_id) | Facts, preferences, experiences. Stored in a Store. |

---

## 3. Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Your Stateful Agent                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   LLM Node   │───▶│  Tool Node   │───▶│  Memory Store    │  │
│  │  (ReAct)     │◀───│  (execute)   │    │  (long-term)     │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│         │                     │                    │           │
│         └─────────────────────┴────────────────────┘           │
│                           │                                     │
│                    ┌──────▼──────┐                               │
│                    │ Checkpointer│  ◀── SQLite (local file)      │
│                    │ (thread_id)│                               │
│                    └────────────┘                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

1. **Graph**: ReAct agent (LLM → tools → LLM loop).
2. **Tools**: File ops, web, code, etc. (similar to OpenClaw).
3. **Checkpointer**: SQLite for local persistence.
4. **Store** (optional): Long-term memory (facts, preferences).
5. **Thread ID**: Stable per user/session so state persists across restarts.

---

## 4. Deployment Options

### Option A: Standalone Python (simplest)

- Run agent as a Python process.
- SQLite checkpointer → single `.db` file.
- No Docker. Good for dev and single-machine use.

### Option B: Docker + SQLite

- Agent in a container.
- SQLite file on a bind-mounted volume.
- Same thread_id across restarts → state persists.

### Option C: Docker + Postgres

- Agent + Postgres in `docker-compose`.
- Better for multi-process or production.
- LangGraph Server can auto-provision Postgres.

---

## 5. Getting Started — Phased Plan

### Phase 1: Foundation (this step)

- [ ] Project setup (venv, `requirements.txt`)
- [ ] Minimal ReAct agent with 1–2 tools
- [ ] SQLite checkpointer
- [ ] Verify state persists across invocations (same `thread_id`)

### Phase 2: Agent + Tools

- [ ] Add tools (file, web, shell, etc.)
- [ ] System prompt for agency
- [ ] Optional: `create_react_agent` from `langgraph.prebuilt`

### Phase 3: Memory

- [ ] Long-term memory (Store)
- [ ] Import Letta memories (format TBD)
- [ ] Memory retrieval in agent flow

### Phase 4: Deployment

- [ ] Docker setup
- [ ] Volume for SQLite/Postgres
- [ ] API or CLI interface

---

## 6. Key Dependencies

```
langgraph>=1.0
langgraph-checkpoint-sqlite>=3.0   # Local persistence
langchain>=0.3                     # Models, tools, messages
langchain-openai                   # or langchain-anthropic
```

---

## 7. References

- [LangGraph README](https://github.com/langchain-ai/langgraph)
- [Quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Memory overview](https://docs.langchain.com/oss/python/langgraph/memory)
- [Durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [Memory Agent template](https://github.com/langchain-ai/memory-agent)
