"""
Run heartbeat on a schedule using APScheduler.

Alternative to Windows Task Scheduler. Keeps running and fires heartbeat every N minutes.

During sleeping hours (default 10 PM – 5 AM) heartbeats are skipped automatically.
Configure the window via env vars:
    HEARTBEAT_WAKE_HOUR   — first hour of waking time, 0-23 (default: 5  → 5:00 AM)
    HEARTBEAT_SLEEP_HOUR  — first hour of sleeping time, 0-23 (default: 22 → 10:00 PM)

Usage:
    python -m scripts.run_heartbeat_scheduler [--interval 60]

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()


def _is_waking_hours() -> bool:
    """Return True if the current time falls within configured waking hours."""
    tz = ZoneInfo(os.environ.get("AGENT_TIMEZONE", "America/New_York"))
    now = datetime.now(tz)
    wake_hour = int(os.environ.get("HEARTBEAT_WAKE_HOUR", "5"))
    sleep_hour = int(os.environ.get("HEARTBEAT_SLEEP_HOUR", "22"))
    return wake_hour <= now.hour < sleep_hour


def run_one_heartbeat():
    if not _is_waking_hours():
        wake_hour = int(os.environ.get("HEARTBEAT_WAKE_HOUR", "5"))
        sleep_hour = int(os.environ.get("HEARTBEAT_SLEEP_HOUR", "22"))
        tz = ZoneInfo(os.environ.get("AGENT_TIMEZONE", "America/New_York"))
        now = datetime.now(tz).strftime("%H:%M")
        print(f"[Heartbeat] Skipping ({now}) — outside waking hours ({wake_hour:02d}:00–{sleep_hour:02d}:00)")
        return

    from src.agent.heartbeat import run_heartbeat

    try:
        run_heartbeat()
        print("[Heartbeat] Cycle complete")
    except Exception as e:
        print(f"[Heartbeat] Error: {e}")


def main():
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

    wake_hour = int(os.environ.get("HEARTBEAT_WAKE_HOUR", "5"))
    sleep_hour = int(os.environ.get("HEARTBEAT_SLEEP_HOUR", "22"))

    scheduler = BlockingScheduler()
    scheduler.add_job(run_one_heartbeat, "interval", minutes=interval, id="heartbeat")
    print(
        f"Heartbeat scheduler: every {interval} minutes, "
        f"active {wake_hour:02d}:00–{sleep_hour:02d}:00. Ctrl+C to stop."
    )
    scheduler.start()


if __name__ == "__main__":
    main()
