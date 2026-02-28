#!/usr/bin/env python
"""
Agent latency profiler — measures where the ~50s response time is going.

Runs each step of the chat() pipeline in isolation, then runs the full
agent.invoke() and reports a breakdown. Does NOT modify any agent code.

Usage:
    python scripts/profile_latency.py
    python scripts/profile_latency.py --message "your test prompt"
    python scripts/profile_latency.py --skip-invoke   # skip full agent call

Steps measured:
  1. Raw LLM call      — baseline API latency + TTFT (no context, no tools)
  2. LLM + system      — same call but with the real core memory system prompt
  3. PostgreSQL ops    — connect, load_messages (with tiktoken), DB write
  4. SQLite ops        — checkpointer init, delete_thread
  5. Full invoke       — real agent.invoke() with tool-call breakdown
  6. Post-invoke       — DB write + Hindsight retain (both in critical path)
  7. Summary           — totals + bottleneck flags
"""
from __future__ import annotations

import argparse
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# ── Bootstrap: add project root to path, load .env ───────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=True)

import os

# ── Timing helpers ────────────────────────────────────────────────────────────

_RESULTS: dict[str, float] = {}   # key → seconds

def _store(key: str, val: float) -> float:
    _RESULTS[key] = val
    return val

@contextmanager
def timed(label: str, key: str | None = None, indent: int = 4):
    t0 = time.perf_counter()
    yield
    dur = time.perf_counter() - t0
    pad = " " * indent
    print(f"{pad}[{dur:6.3f}s] {label}")
    if key:
        _store(key, dur)

def sep(title: str = ""):
    bar = "─" * 68
    if title:
        print(f"\n{bar}\n  {title}\n{bar}")
    else:
        print(bar)


# ── Step 1: Raw LLM call ──────────────────────────────────────────────────────

def step1_raw_llm(message: str) -> None:
    sep("STEP 1 — Raw LLM API call (no history, no tools, no system prompt)")

    from openai import OpenAI

    api_key  = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
    model    = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini")

    print(f"    model:    {model}")
    print(f"    base_url: {base_url or '(OpenAI default)'}")

    client = OpenAI(api_key=api_key, base_url=base_url)
    msgs = [{"role": "user", "content": message}]

    # Non-streaming — total round trip
    print("\n    Non-streaming:")
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model, messages=msgs, temperature=0, max_tokens=30
    )
    dur = _store("llm_raw_total", time.perf_counter() - t0)
    print(f"    [{dur:6.3f}s] total (prompt={resp.usage.prompt_tokens} tok, "
          f"completion={resp.usage.completion_tokens} tok)")

    # Streaming — TTFT + total
    print("\n    Streaming (TTFT):")
    t0 = time.perf_counter()
    ttft = None
    full_text = ""
    chunk_count = 0
    with client.chat.completions.create(
        model=model, messages=msgs, temperature=0, max_tokens=30, stream=True
    ) as stream:
        for chunk in stream:
            chunk_count += 1
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                if ttft is None:
                    ttft = _store("llm_raw_ttft", time.perf_counter() - t0)
                full_text += delta
    total = _store("llm_raw_stream_total", time.perf_counter() - t0)

    if ttft is not None:
        print(f"    [{ttft:6.3f}s] TTFT (time to first token)")
    print(f"    [{total:6.3f}s] total streaming")
    print(f"    [{chunk_count:>6}] chunks received")
    print(f"    response: {repr(full_text.strip()[:80])}")


# ── Step 2: LLM with real system prompt ──────────────────────────────────────

def step2_llm_with_system(message: str) -> None:
    sep("STEP 2 — LLM call with real core memory system prompt")

    from openai import OpenAI
    from src.agent.core_memory import get_all_blocks
    from src.agent.graph import _format_current_time, AGENT_TIMEZONE

    api_key  = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
    model    = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini")

    # Build system prompt exactly as the agent does
    t0 = time.perf_counter()
    blocks = get_all_blocks()
    mem_dur = _store("mem_load", time.perf_counter() - t0)

    current_time = datetime.now(AGENT_TIMEZONE)
    time_str = _format_current_time(current_time)

    parts = [f"# Current Time\n\nIt is currently: {time_str}\n\n---\n\n"]
    sys_instr = blocks.get("system_instructions", "").strip()
    if sys_instr:
        parts.append(f"# System Instructions (READ ONLY)\n\n{sys_instr}\n\n---\n\n")
    parts.append("# Core Memory\n\n")
    for name, label in [("user", "User"), ("identity", "Identity"), ("ideaspace", "Ideaspace")]:
        content = blocks.get(name, "").strip()
        parts.append(f"## {label}\n{content or '(empty)'}\n")

    system_content = "".join(parts)
    approx_tokens = len(system_content) // 4

    print(f"    [{mem_dur:6.3f}s] get_all_blocks() (core memory from Postgres)")
    print(f"    system prompt: {len(system_content)} chars (~{approx_tokens} tokens)")

    client = OpenAI(api_key=api_key, base_url=base_url)
    msgs = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": message},
    ]

    print("\n    Streaming (TTFT with system prompt):")
    t0 = time.perf_counter()
    ttft = None
    full_text = ""
    with client.chat.completions.create(
        model=model, messages=msgs, temperature=0, max_tokens=30, stream=True
    ) as stream:
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                if ttft is None:
                    ttft = _store("llm_sys_ttft", time.perf_counter() - t0)
                full_text += delta
    total = _store("llm_sys_total", time.perf_counter() - t0)

    raw_ttft = _RESULTS.get("llm_raw_ttft", 0)
    if ttft is not None:
        delta_ttft = ttft - raw_ttft
        print(f"    [{ttft:6.3f}s] TTFT  (Δ {delta_ttft:+.3f}s vs raw)")
    print(f"    [{total:6.3f}s] total streaming")
    print(f"    response: {repr(full_text.strip()[:80])}")


# ── Step 3: PostgreSQL operations ─────────────────────────────────────────────

def step3_postgres() -> None:
    sep("STEP 3 — PostgreSQL operations")

    from src.agent.db import get_connection, load_messages, append_messages

    # Connection latency
    t0 = time.perf_counter()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    _store("pg_connect", time.perf_counter() - t0)
    print(f"    [{_RESULTS['pg_connect']:6.3f}s] connect + SELECT 1 (round-trip to Railway)")

    # load_messages — real history, includes tiktoken counting
    t0 = time.perf_counter()
    rows = load_messages("main", max_tokens=200_000)
    _store("pg_load", time.perf_counter() - t0)
    total_chars = sum(len(r["content"]) for r in rows)
    total_tokens_approx = total_chars // 4
    print(f"    [{_RESULTS['pg_load']:6.3f}s] load_messages('main')  "
          f"→ {len(rows)} messages, ~{total_chars} chars (~{total_tokens_approx} tokens)")
    print(f"                            (includes tiktoken count for sliding window)")

    # DB write — in critical path after agent.invoke()
    t0 = time.perf_counter()
    append_messages(
        "__profile_test__",
        [("user", "profiler test", None, None), ("assistant", "OK", None, None)],
    )
    _store("pg_write", time.perf_counter() - t0)
    print(f"    [{_RESULTS['pg_write']:6.3f}s] append_messages (2 messages written)")

    # Cleanup
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE thread_id = '__profile_test__'")


# ── Step 4: SQLite checkpointer ───────────────────────────────────────────────

def step4_sqlite() -> None:
    sep("STEP 4 — SQLite checkpointer operations")

    from src.agent.graph import get_checkpointer

    t0 = time.perf_counter()
    cp = get_checkpointer()
    _store("sqlite_init", time.perf_counter() - t0)
    print(f"    [{_RESULTS['sqlite_init']:6.3f}s] get_checkpointer() (open SQLite conn)")

    t0 = time.perf_counter()
    cp.delete_thread("main")
    _store("sqlite_delete", time.perf_counter() - t0)
    print(f"    [{_RESULTS['sqlite_delete']:6.3f}s] delete_thread('main')")
    print(f"                            (called once per chat() to prevent history merge)")


# ── Step 5: Full agent.invoke() ───────────────────────────────────────────────

def step5_full_invoke(agent, message: str) -> None:
    sep("STEP 5 — Full agent.invoke() with tool-call breakdown")

    from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
    from src.agent.db import load_messages
    from src.agent.graph import (
        CONTEXT_WINDOW_TOKENS, AGENT_TIMEZONE,
        _db_to_langchain, _format_current_time, get_checkpointer,
    )

    current_time = datetime.now(AGENT_TIMEZONE)
    time_str = _format_current_time(current_time)

    # Load real history (same as chat() does)
    t0 = time.perf_counter()
    rows = load_messages("main", max_tokens=CONTEXT_WINDOW_TOKENS)
    history = _db_to_langchain(rows)
    db_pre = _store("invoke_db_pre", time.perf_counter() - t0)
    print(f"    [{db_pre:6.3f}s] load_messages (pre-invoke, includes tiktoken)")

    new_msg = HumanMessage(content=f"[{time_str}]\n{message}")
    messages_list = history + [new_msg]
    context_chars = sum(len(str(m.content)) for m in messages_list)
    print(f"    context fed to LLM: ~{context_chars} chars (~{context_chars // 4} tokens)")

    # SQLite delete
    t0 = time.perf_counter()
    get_checkpointer().delete_thread("__profile_test__")
    sqlite_pre = _store("invoke_sqlite_pre", time.perf_counter() - t0)
    print(f"    [{sqlite_pre:6.3f}s] sqlite delete_thread (pre-invoke)")

    # The actual invoke
    invoke_state = {"messages": messages_list}
    run_config = {"configurable": {"thread_id": "__profile_test__"}}

    print(f"\n    Calling agent.invoke() — watch for tool calls ...")
    t0 = time.perf_counter()
    result = agent.invoke(invoke_state, config=run_config)
    invoke_dur = _store("invoke_llm", time.perf_counter() - t0)
    print(f"    [{invoke_dur:6.3f}s] agent.invoke() returned")

    # Analyze returned messages to count LLM round-trips and tool calls
    result_msgs = result.get("messages", [])
    ai_messages   = [m for m in result_msgs if isinstance(m, AIMessage)]
    tool_messages = [m for m in result_msgs if isinstance(m, ToolMessage)]

    _store("invoke_llm_calls",  float(len(ai_messages)))
    _store("invoke_tool_calls", float(len(tool_messages)))

    print(f"\n    LLM round-trips:  {len(ai_messages)}")
    print(f"    Tool calls made:  {len(tool_messages)}")

    # Show which tools were called and in what order
    if tool_messages or len(ai_messages) > 1:
        print(f"\n    Tool call trace:")
        for msg in result_msgs:
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "?")
                    args = str(tc.get("args", {}))[:60]
                    print(f"      → called tool: {name}({args})")
            elif isinstance(msg, ToolMessage):
                preview = str(msg.content)[:80].replace("\n", " ")
                print(f"      ← tool result: {preview}")
    else:
        print(f"    (no tool calls — direct response)")

    # Final response
    final = ai_messages[-1].content if ai_messages else "(none)"
    if isinstance(final, list):
        final = " ".join(b.get("text", "") for b in final if isinstance(b, dict))
    print(f"\n    response: {repr(str(final).strip()[:120])}")

    # Cleanup test checkpoint
    get_checkpointer().delete_thread("__profile_test__")


# ── Step 6: Post-invoke operations ────────────────────────────────────────────

def step6_post_invoke(message: str) -> None:
    sep("STEP 6 — Post-invoke operations (also in critical path)")

    from src.agent.db import append_messages
    from src.agent.hindsight import retain_exchange

    # DB write — happens after every agent response
    t0 = time.perf_counter()
    append_messages(
        "__profile_test__",
        [("user", message, None, None), ("assistant", "OK", None, None)],
        user_display_name=os.environ.get("USER_DISPLAY_NAME", "User"),
    )
    pg_write = _store("post_pg_write", time.perf_counter() - t0)
    print(f"    [{pg_write:6.3f}s] append_messages (user + assistant to Postgres)")

    # Cleanup
    from src.agent.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE thread_id = '__profile_test__'")

    # Hindsight retain — happens after every exchange, synchronous
    t0 = time.perf_counter()
    result = retain_exchange(
        bank_id=None,
        user_content=message,
        assistant_content="OK",
        thread_id="__profile_test__",
        user_id="local:profiler",
        channel_type="local",
    )
    hindsight_dur = _store("post_hindsight", time.perf_counter() - t0)
    status = "retained" if result else "skipped/unavailable"
    print(f"    [{hindsight_dur:6.3f}s] retain_exchange (Hindsight) — {status}")


# ── Step 7: Summary ───────────────────────────────────────────────────────────

def step7_summary() -> None:
    sep("SUMMARY")

    r = _RESULTS
    llm_raw       = r.get("llm_raw_stream_total", 0)
    llm_raw_ttft  = r.get("llm_raw_ttft", 0)
    llm_sys       = r.get("llm_sys_total", 0)
    llm_sys_ttft  = r.get("llm_sys_ttft", 0)
    pg_connect    = r.get("pg_connect", 0)
    pg_load       = r.get("pg_load", 0)
    pg_write      = r.get("post_pg_write", 0)
    sqlite_del    = r.get("sqlite_delete", 0)
    mem_load      = r.get("mem_load", 0)
    invoke        = r.get("invoke_llm", 0)
    llm_calls     = int(r.get("invoke_llm_calls", 0))
    tool_calls    = int(r.get("invoke_tool_calls", 0))
    hindsight     = r.get("post_hindsight", 0)

    print(f"  {'Component':<42} {'Time':>8}  {'Notes'}")
    print(f"  {'─'*42} {'─'*8}  {'─'*20}")
    print(f"  {'Raw LLM TTFT (no context)':<42} {llm_raw_ttft:>7.2f}s")
    print(f"  {'Raw LLM total (no context)':<42} {llm_raw:>7.2f}s")
    print(f"  {'LLM TTFT with system prompt':<42} {llm_sys_ttft:>7.2f}s  Δ{llm_sys_ttft - llm_raw_ttft:+.2f}s vs raw")
    print(f"  {'LLM total with system prompt':<42} {llm_sys:>7.2f}s  Δ{llm_sys - llm_raw:+.2f}s vs raw")
    print(f"  {'Postgres connect + ping':<42} {pg_connect:>7.3f}s")
    print(f"  {'load_messages (tiktoken included)':<42} {pg_load:>7.3f}s")
    print(f"  {'Core memory get_all_blocks()':<42} {mem_load:>7.3f}s")
    print(f"  {'SQLite delete_thread':<42} {sqlite_del:>7.3f}s")
    print(f"  {'agent.invoke() total':<42} {invoke:>7.2f}s  {llm_calls} LLM calls, {tool_calls} tool calls")
    print(f"  {'append_messages (post-invoke DB write)':<42} {pg_write:>7.3f}s")
    print(f"  {'retain_exchange (Hindsight)':<42} {hindsight:>7.3f}s")

    # Estimated full chat() time (reproduce the actual call sequence)
    estimated_total = pg_load + sqlite_del + invoke + pg_write + hindsight
    print(f"\n  {'Estimated chat() total':<42} {estimated_total:>7.2f}s")
    print(f"  {'(= pg_load + sqlite_del + invoke + pg_write + hindsight)'}")

    # Bottleneck flags
    print(f"\n  BOTTLENECK FLAGS:")
    flags = 0

    if llm_raw_ttft > 5:
        print(f"  ⚠  High TTFT ({llm_raw_ttft:.1f}s) — Chutes AI queue or cold start latency")
        flags += 1
    if llm_raw > 20:
        print(f"  ⚠  Slow raw LLM ({llm_raw:.1f}s) — model generation speed or token limit")
        flags += 1
    if llm_calls > 1:
        est_llm_total = llm_raw * llm_calls
        print(f"  ⚠  {llm_calls} LLM round-trips — tool calls multiply latency "
              f"(~{est_llm_total:.0f}s of LLM time alone)")
        flags += 1
    if pg_connect > 0.3:
        print(f"  ⚠  Slow Postgres connect ({pg_connect:.2f}s) — Railway region or cold connection")
        flags += 1
    if pg_load > 1.0:
        print(f"  ⚠  Slow load_messages ({pg_load:.2f}s) — large history or slow Railway DB")
        flags += 1
    if hindsight > 1.0:
        print(f"  ⚠  Slow Hindsight retain ({hindsight:.2f}s) — adds to every response")
        flags += 1

    if flags == 0:
        print(f"  ✓  No obvious single bottleneck — latency likely split across components")

    print(f"\n  QUICK WINS:")
    if llm_calls > 1:
        print(f"  →  Agent called {llm_calls} tools per response — "
              f"system prompt may be triggering unnecessary tool use")
    if llm_raw_ttft > 5 and llm_raw < 15:
        print(f"  →  High TTFT but fast generation — try a different Chutes endpoint or model")
    if llm_sys_ttft - llm_raw_ttft > 2:
        print(f"  →  System prompt adding {llm_sys_ttft - llm_raw_ttft:.1f}s to TTFT — "
              f"shorter core memory blocks would help")
    if pg_load > 0.5:
        print(f"  →  load_messages is slow — consider reducing CONTEXT_WINDOW_TOKENS "
              f"or archiving old messages")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile agent latency — find the 50s bottleneck",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--message", "-m",
        default="Reply with exactly one word: OK",
        help="Test message (default: simple reply prompt to avoid tool calls)",
    )
    parser.add_argument(
        "--skip-invoke",
        action="store_true",
        help="Skip the full agent.invoke() test (steps 5-6) — faster for DB/LLM-only profiling",
    )
    args = parser.parse_args()

    print("\n" + "=" * 68)
    print("  AGENT LATENCY PROFILER")
    print("=" * 68)
    print(f"  message:   {repr(args.message)}")
    print(f"  timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    step1_raw_llm(args.message)
    step2_llm_with_system(args.message)
    step3_postgres()
    step4_sqlite()

    if not args.skip_invoke:
        print("\n  Building agent ...")
        from src.agent.graph import build_agent
        t0 = time.perf_counter()
        agent = build_agent()
        build_dur = _store("build_agent", time.perf_counter() - t0)
        print(f"    [{build_dur:6.3f}s] build_agent()")

        step5_full_invoke(agent, args.message)
        step6_post_invoke(args.message)

    step7_summary()
    print()


if __name__ == "__main__":
    main()
