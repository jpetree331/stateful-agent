#!/usr/bin/env python3
"""
Run both Railway Postgres and Hindsight backups. Use this for the weekly schedule.

Usage:
  python scripts/backup_all.py
  python scripts/backup_all.py --schedule   # Create Windows Task (Sundays 2 AM)
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M",
)
logger = logging.getLogger("backup_all")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Railway + Hindsight backups")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Create Windows Task Scheduler entry (Sundays 2 AM)",
    )
    args = parser.parse_args()

    if args.schedule:
        # Remove old single-backup tasks to avoid duplicates
        for old_task in ["AgentPostgresBackup", "AgentHindsightBackup"]:
            subprocess.run(
                ["schtasks", "/delete", "/tn", old_task, "/f"],
                capture_output=True,
            )
        python_exe = Path(sys.executable)
        cmd = f'cmd /c "cd /d {_PROJECT_ROOT} && "{python_exe}" scripts/backup_all.py"'
        try:
            result = subprocess.run(
                [
                    "schtasks", "/create",
                    "/tn", "AgentBackups",
                    "/tr", cmd,
                    "/sc", "weekly",
                    "/d", "SUN",
                    "/st", "02:00",
                    "/f",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info(
                    "Scheduled AgentBackups (Sundays 2:00 AM) — runs Postgres + Hindsight. "
                    "To remove: schtasks /delete /tn AgentBackups /f"
                )
                return 0
            logger.error(f"schtasks failed: {result.stderr or result.stdout}")
            return 1
        except Exception as e:
            logger.error(f"Could not schedule: {e}")
            return 1

    # Run both backups
    scripts = ["scripts/backup_postgres.py", "scripts/backup_hindsight.py"]
    failed = 0
    for script in scripts:
        logger.info(f"Running {script}...")
        r = subprocess.run(
            [sys.executable, script],
            cwd=_PROJECT_ROOT,
        )
        if r.returncode != 0:
            logger.warning(f"{script} failed (exit {r.returncode})")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
