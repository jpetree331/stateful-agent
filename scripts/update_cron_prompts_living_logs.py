"""
update_cron_prompts_living_logs.py — Append Living Logs instructions to the
1 AM Wonder (Phase 1) and 2 AM Reflect (Phase 2) cron job prompts.

Run once after migrate_living_logs.py.

What it does:
  - Finds cron jobs named "1 AM Wonder" and "2 AM Reflect" in the database
  - Appends the STEP 0 (gather living log data) block to Phase 1
  - Appends the cleanup block (update threads/lore/positions) to Phase 2
  - Idempotent: checks for the marker string before appending
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from src.agent.db import get_connection

# ── Additions ─────────────────────────────────────────────────────────────────

PHASE1_ADDITION = """

---

## STEP 0 — GATHER LIVING LOG DATA (do this before any reflection)

Call these four queries at the start of this session to gather your lived material:

  query_living_logs(table='tension_log', days_back=7)
  query_living_logs(table='loose_threads', days_back=7)
  query_living_logs(table='evolving_positions', days_back=30)
  query_living_logs(table='shared_lore', days_back=30)

These are your lived friction, open questions, intellectual positions, and relationship
continuity from the past week. They are more honest than anything you said confidently.
Use them as primary material for your synthesis and wonder writing.
"""

PHASE2_ADDITION = """

---

## LIVING LOGS CLEANUP (do this after core memory updates)

After executing any core memory updates, also:

  - Call update_thread_status for any Loose Threads that were resolved or advanced this week
  - Call update_shared_lore for any Shared Lore entries that evolved or should be retired
  - If any tension_log entries surfaced a position worth recording, call log_position
"""

PHASE1_MARKER = "STEP 0 — GATHER LIVING LOG DATA"
PHASE2_MARKER = "LIVING LOGS CLEANUP"


def update_prompt(job_name: str, addition: str, marker: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, instructions FROM cron_jobs WHERE name = %s",
                (job_name,),
            )
            row = cur.fetchone()

    if not row:
        print(f"  SKIP: cron job '{job_name}' not found in database.")
        return

    job_id = row["id"]
    current = row["instructions"] or ""

    if marker in current:
        print(f"  SKIP: '{job_name}' (id={job_id}) already has living logs block.")
        return

    updated = current + addition
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cron_jobs SET instructions = %s, updated_at = NOW() WHERE id = %s",
                (updated, job_id),
            )
    print(f"  UPDATED: '{job_name}' (id={job_id}) — living logs block appended.")


def main() -> None:
    print("Updating cron job prompts with Living Logs instructions...\n")
    update_prompt("1 AM Wonder", PHASE1_ADDITION, PHASE1_MARKER)
    update_prompt("2 AM Reflect", PHASE2_ADDITION, PHASE2_MARKER)
    print("\nDone.")


if __name__ == "__main__":
    main()
