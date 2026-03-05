# Examples — Starting Points for Your Agent

This folder contains example templates and prompts you can use as a starting point. **These files are intended for you to copy, customize, and make your own.** They live in the repo so they survive syncs and are always available.

## Memory Templates

**[`memory/`](memory/)** — Core memory blocks (system instructions, identity, user, ideaspace)

- `NEWSYSINSTRUCT.txt` — Default system instructions (memory architecture, privacy, autonomy)
- `SYSINSTRUCT_EXAMPLE.txt` — **Advanced example** with Living Logs (tension_log, loose_threads, evolving_positions, shared_lore, private_journal). Generic privacy rules. Use as a starting point for a more introspective, relationship-oriented agent.
- `IDENTITY.txt`, `USER.txt`, `IDEASPACE.txt` — Placeholder blocks

See [`memory/README.md`](memory/README.md) for import instructions.

## Heartbeat Prompts

**[`heartbeat/`](heartbeat/)** — Dual-phase autonomous prompts

- `HEARTBEAT_PROMPTS_EXAMPLE.md` — **Example** Wonder + Work prompts. Two phases: exploration (curiosity, research, philosophical wandering) and agency (projects, tasks, preparation for the user). Copy to a `.txt` file and set `HEARTBEAT_PROMPT_PATH` in `.env`, or use as inspiration for cron job instructions.

## Quick Start

1. **Memory**: Copy `examples/memory/SYSINSTRUCT_EXAMPLE.txt` to `NEWSYSINSTRUCT.txt` (or merge sections into your existing file), customize, then:
   ```bash
   python scripts/import_core_memory.py --path examples/memory
   ```

2. **Heartbeat**: Copy `examples/heartbeat/HEARTBEAT_PROMPTS_EXAMPLE.md` to e.g. `HEARTBEAT.txt`, customize for your timezone and tools, then set in `.env`:
   ```bash
   HEARTBEAT_PROMPT_PATH=C:\path\to\your\HEARTBEAT.txt
   ```

Or create cron jobs (e.g. "1 AM Wonder", "2 AM Reflect") and paste the relevant sections into their instructions.
