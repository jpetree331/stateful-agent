#!/usr/bin/env python3
"""
Backup the Railway PostgreSQL database. Keeps the last N backups, deletes older ones.

Designed for weekly cron runs. Uses pg_dump for a full database dump (schema + data).

Usage:
  python scripts/backup_postgres.py
  python scripts/backup_postgres.py --keep 6

Cron (weekly, e.g. Sunday 2 AM):
  python scripts/backup_postgres.py --schedule

  Or manually:
  schtasks /create /tn "RowanPostgresBackup" /tr "cmd /c \"cd /d E:\\git\\LANGGRAPH && .venv\\Scripts\\python.exe scripts\\backup_postgres.py\"" /sc weekly /d SUN /st 02:00 /f

Requires: pg_dump (PostgreSQL client tools). Install from https://www.postgresql.org/download/windows/
  Or: winget install PostgreSQL.PostgreSQL
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Project root and .env
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "backups"  # Override via BACKUP_OUTPUT_DIR env
_OUTPUT_DIR = Path(os.environ.get("BACKUP_OUTPUT_DIR") or str(_DEFAULT_OUTPUT))
_KEEP_COUNT = 4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M",
)
logger = logging.getLogger("backup_postgres")


def _load_env() -> None:
    """Load .env from project root."""
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env", override=True)


def _find_pg_dump() -> str | None:
    """Find pg_dump executable. Returns path or None."""
    exe = shutil.which("pg_dump")
    if exe:
        return exe
    # Common Windows PostgreSQL paths
    for base in [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "PostgreSQL",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "PostgreSQL",
    ]:
        if base.exists():
            for sub in sorted(base.iterdir(), reverse=True):  # prefer newest version
                candidate = sub / "bin" / "pg_dump.exe"
                if candidate.exists():
                    return str(candidate)
    return None


def _run_backup(db_url: str, output_path: Path) -> bool:
    """Run pg_dump. Returns True on success."""
    pg_dump = _find_pg_dump()
    if not pg_dump:
        logger.error(
            "pg_dump not found. Install PostgreSQL client tools:\n"
            "  winget install PostgreSQL.PostgreSQL\n"
            "  Or: https://www.postgresql.org/download/windows/"
        )
        return False

    try:
        result = subprocess.run(
            [pg_dump, db_url, "-Fc", "-f", str(output_path)],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            logger.error(f"pg_dump failed: {result.stderr or result.stdout}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out after 10 minutes")
        return False
    except Exception as e:
        logger.error(f"pg_dump error: {e}")
        return False


def _prune_old_backups(keep: int) -> None:
    """Keep only the last `keep` backup files, delete older ones."""
    if not _OUTPUT_DIR.exists():
        return
    pattern = "postgres-*.dump"
    files = sorted(
        _OUTPUT_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    to_delete = files[keep:]
    for p in to_delete:
        try:
            p.unlink()
            logger.info(f"Pruned old backup: {p.name}")
        except OSError as e:
            logger.warning(f"Could not delete {p.name}: {e}")


def _schedule_weekly_task() -> bool:
    """Create Windows Task Scheduler entry for weekly backup (Sunday 2 AM). Returns True on success."""
    python_exe = Path(sys.executable)
    project_root = _PROJECT_ROOT
    cmd = f'cmd /c "cd /d {project_root} && "{python_exe}" scripts/backup_postgres.py"'
    task_name = "AgentPostgresBackup"
    try:
        result = subprocess.run(
            [
                "schtasks", "/create",
                "/tn", task_name,
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
                f"Scheduled weekly backup: {task_name} (Sundays 2:00 AM). "
                f"To remove: schtasks /delete /tn {task_name} /f"
            )
            return True
        logger.error(f"schtasks failed: {result.stderr or result.stdout}")
        return False
    except Exception as e:
        logger.error(f"Could not schedule task: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup Railway PostgreSQL database")
    parser.add_argument(
        "--keep",
        type=int,
        default=_KEEP_COUNT,
        help=f"Number of backups to keep (default: {_KEEP_COUNT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: BACKUP_OUTPUT_DIR env or ./backups)",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Create Windows Task Scheduler entry for weekly backup (Sundays 2 AM)",
    )
    args = parser.parse_args()

    if args.schedule:
        return 0 if _schedule_weekly_task() else 1

    _load_env()
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        logger.error("DATABASE_URL not set in .env")
        return 1

    output_dir = args.output_dir or _OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    output_path = output_dir / f"postgres-{timestamp}.dump"

    logger.info(f"Starting backup to {output_path}")
    if not _run_backup(db_url, output_path):
        return 1

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Backup complete: {output_path.name} ({size_mb:.2f} MB)")

    _prune_old_backups(args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
