"""
Run heartbeat on a schedule using APScheduler.

Alternative to Windows Task Scheduler. Keeps running and fires heartbeat every N minutes.
Automatically selects the heartbeat mode based on time of day.

Time windows are configured in data/heartbeat_config.json (editable from the Hbeat dashboard tab)
or via env vars as fallback:
    HEARTBEAT_WONDER_START_HOUR  — start of Wonder window (default: 22 → 10 PM)
    HEARTBEAT_WONDER_END_HOUR    — end of Wonder window   (default:  3 →  3 AM)
    HEARTBEAT_WORK_START_HOUR    — start of Work window   (default:  3 →  3 AM)
    HEARTBEAT_WORK_END_HOUR      — end of Work window     (default:  6 →  6 AM)
    HEARTBEAT_DAY_INTERVAL_MINUTES   — interval during day   (default: 60)
    HEARTBEAT_NIGHT_INTERVAL_MINUTES — interval overnight    (default: 90)

Default schedule:
    10 PM –  3 AM : Wonder  (overnight exploration)
     3 AM –  6 AM : Work    (agent prepares before user comes online)
     6 AM – 10 PM : Day     (user likely online; every day_interval minutes)

The scheduler re-reads config on each tick — dashboard changes take effect without restart.
For one-off daytime heartbeats (e.g. a midday Work or Wonder), create named cron jobs
in the dashboard with the full prompt in the instructions field.

Usage:
    python -m scripts.run_heartbeat_scheduler [--interval N]

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

_TZ = ZoneInfo(os.environ.get("AGENT_TIMEZONE", "America/New_York"))

# Re-read config on every tick so dashboard changes take effect without restart.
# The scheduler reschedules itself when the interval changes.
_current_interval: int = 0
_scheduler_ref: "BlockingScheduler | None" = None


def _current_hour() -> int:
    return datetime.now(_TZ).hour


def _get_mode_and_interval() -> tuple[str, int]:
    """Return (mode, interval_minutes) for the current moment from live config."""
    from src.agent.heartbeat_config import load_config, get_mode_for_hour
    cfg = load_config()
    hour = _current_hour()
    mode = get_mode_for_hour(hour, cfg)
    # Night window = wonder or work; day window = day
    interval = cfg["night_interval"] if mode in ("wonder", "work") else cfg["day_interval"]
    return mode, interval


def run_one_heartbeat():
    global _current_interval, _scheduler_ref

    mode, interval = _get_mode_and_interval()

    # If the interval has changed, reschedule the job dynamically
    if _scheduler_ref and interval != _current_interval and _current_interval != 0:
        try:
            _scheduler_ref.reschedule_job("heartbeat", trigger="interval", minutes=interval)
            print(f"[Heartbeat] Interval changed: {_current_interval}m -> {interval}m")
            _current_interval = interval
        except Exception as e:
            print(f"[Heartbeat] Could not reschedule: {e}")

    from src.agent.heartbeat import run_heartbeat
    try:
        run_heartbeat(mode=mode)
        print(f"[Heartbeat:{mode}] Cycle complete")
    except Exception as e:
        print(f"[Heartbeat:{mode}] Error: {e}")


def main():
    global _current_interval, _scheduler_ref

    from src.agent.heartbeat_config import load_config
    cfg = load_config()

    # --interval flag overrides config (useful for one-off testing)
    parser = argparse.ArgumentParser(description="Run heartbeat on schedule")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override interval in minutes (default: from config/env)",
    )
    args = parser.parse_args()

    # Starting interval: use CLI override, else use day_interval as the initial value
    # (the first tick will pick the right interval for the current time)
    start_interval = args.interval or cfg["day_interval"]
    _current_interval = start_interval

    scheduler = BlockingScheduler()
    _scheduler_ref = scheduler
    scheduler.add_job(run_one_heartbeat, "interval", minutes=start_interval, id="heartbeat")

    print(
        f"Heartbeat scheduler started\n"
        f"  Wonder window : {cfg['wonder_start']:02d}:00 - {cfg['wonder_end']:02d}:00  "
        f"(every {cfg['night_interval']} min)\n"
        f"  Work window   : {cfg['work_start']:02d}:00 - {cfg['work_end']:02d}:00  "
        f"(inside night window)\n"
        f"  Day           : all other hours  (every {cfg['day_interval']} min)\n"
        f"  Starting interval: {start_interval} min. Ctrl+C to stop."
    )
    scheduler.start()


if __name__ == "__main__":
    main()
