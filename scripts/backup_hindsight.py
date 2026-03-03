#!/usr/bin/env python3
"""
Backup Hindsight memories from the local Docker container.

Uses pg_dump inside the hindsight-db container. Read-only — does not modify
or delete anything in the Hindsight database. Only prunes old local backup files.

Usage:
  python scripts/backup_hindsight.py
  python scripts/backup_hindsight.py --keep 6

Requires: Docker with hindsight-db container running (Hindsight server).
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "backups"  # Override via BACKUP_OUTPUT_DIR env
_OUTPUT_DIR = Path(os.environ.get("BACKUP_OUTPUT_DIR") or str(_DEFAULT_OUTPUT))
_KEEP_COUNT = 4
_CONTAINER = os.environ.get("HINDSIGHT_CONTAINER", "hindsight-db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M",
)
logger = logging.getLogger("backup_hindsight")


def _run_backup(output_path: Path) -> bool:
    """Run pg_dump inside hindsight-db container. Returns True on success."""
    try:
        result = subprocess.run(
            [
                "docker", "exec", _CONTAINER,
                "pg_dump", "-U", "hindsight_user", "-d", "hindsight_db",
            ],
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
            logger.error(f"pg_dump failed: {err}")
            return False
        output_path.write_bytes(result.stdout)
        return True
    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out after 10 minutes")
        return False
    except FileNotFoundError:
        logger.error(
            "Docker not found or hindsight-db container not running. "
            "Start Hindsight first: docker run ... hindsight"
        )
        return False
    except Exception as e:
        logger.error(f"Backup error: {e}")
        return False


def _prune_old_backups(output_dir: Path, keep: int) -> None:
    """Keep only the last `keep` Hindsight backup files."""
    if not output_dir.exists():
        return
    pattern = "hindsight-*.sql"
    files = sorted(
        output_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in files[keep:]:
        try:
            p.unlink()
            logger.info(f"Pruned old backup: {p.name}")
        except OSError as e:
            logger.warning(f"Could not delete {p.name}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup Hindsight memories from Docker")
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
    args = parser.parse_args()

    output_dir = args.output_dir or _OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    output_path = output_dir / f"hindsight-{timestamp}.sql"

    logger.info(f"Starting Hindsight backup to {output_path}")
    if not _run_backup(output_path):
        return 1

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Backup complete: {output_path.name} ({size_mb:.2f} MB)")

    _prune_old_backups(output_dir, args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
