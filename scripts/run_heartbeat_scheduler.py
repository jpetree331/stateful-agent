"""
Run heartbeat on a schedule using APScheduler.

Alternative to Windows Task Scheduler. Keeps running and fires heartbeat every N minutes.

Usage:
    python -m scripts.run_heartbeat_scheduler [--interval 60]

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()


def run_one_heartbeat():
    from src.agent.heartbeat import run_heartbeat

    try:
        run_heartbeat()
        print("[Heartbeat] Cycle complete")
    except Exception as e:
        print(f"[Heartbeat] Error: {e}")


def main():
    import os
    env_default = int(os.environ.get("HEARTBEAT_INTERVAL_MINUTES", "60"))

    parser = argparse.ArgumentParser(description="Run heartbeat on schedule")
    parser.add_argument(
        "--interval",
        type=int,
        default=env_default,
        help=f"Minutes between heartbeats (default: {env_default}, from HEARTBEAT_INTERVAL_MINUTES env var)",
    )
    args = parser.parse_args()
    interval = max(1, args.interval)

    scheduler = BlockingScheduler()
    scheduler.add_job(run_one_heartbeat, "interval", minutes=interval, id="heartbeat")
    print(f"Heartbeat scheduler: every {interval} minutes. Ctrl+C to stop.")
    scheduler.start()


if __name__ == "__main__":
    main()
