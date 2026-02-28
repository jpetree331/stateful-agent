# Memory Files — Example Templates

This folder contains template files for the agent's core memory blocks. Use these to bootstrap your agent before the first conversation, or import them to seed the memory system with initial content.

## Files

| File | Block | Purpose |
|------|-------|---------|
| `NEWSYSINSTRUCT.txt` | `system_instructions` | Read-only behavioral guidelines. **The most important file.** Start here. |
| `IDENTITY.txt` | `identity` | The agent's self-concept, values, and personality |
| `USER.txt` | `user` | Information about the primary user |
| `IDEASPACE.txt` | `ideaspace` | Working memory — ongoing projects and open threads |

## How to Import

From the project root:

```bash
python scripts/import_core_memory.py --path examples/memory
```

This will import all four files into the PostgreSQL database. After importing, start the agent normally and the memory will be in context.

### Dry-run (preview without importing)

```bash
python scripts/import_core_memory.py --path examples/memory --dry-run
```

### Import only system instructions

You can also edit blocks directly in the dashboard (Memory tab) without using this script. The script is mainly useful for initial setup or bulk updates.

## Customizing System Instructions

`NEWSYSINSTRUCT.txt` is the most impactful file. It shapes the agent's personality, how it handles memory, privacy rules, and how proactive it is.

**Things you should customize:**

1. **Self-description / Mission** (top of the file) — Write who your agent is and what its purpose is. This gets loaded into every conversation. Keep it meaningful but concise.

2. **Timezone** — Change the timezone section to match your local timezone (e.g., `America/Chicago`, `Europe/London`, `Asia/Tokyo`). Or point it to the `AGENT_TIMEZONE` env var.

3. **Privacy rules** — Adjust the privacy section to match what you consider sensitive for your use case. The example includes spiritual matters and mental health — add or remove categories as appropriate.

4. **Communication style** — The behavioral guidelines section can be tuned to match how you want the agent to communicate.

**Things to leave as-is:**

- The `<base_instructions>` XML block — this is functional, not just descriptive
- The memory architecture section — the tool names must match the actual tools
- The group chat / `is_group_chat` logic — this is used by the code

## After Import

1. Restart the agent (`python -m src.agent.graph` or restart the API server)
2. The system instructions are loaded fresh into every conversation — changes take effect immediately after import
3. The other three blocks (`user`, `identity`, `ideaspace`) can also be edited live via the dashboard Memory tab

## Notes

- System instructions are **read-only** for the agent — only you (via the dashboard or this script) can edit them
- The `user`, `identity`, and `ideaspace` blocks can be edited by both you and the agent
- All blocks support markdown formatting
- There's no size limit, but keep system instructions under ~5,000 tokens for best results (they're loaded on every turn)
