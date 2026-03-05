"""
Backfill journal_entries from Rowan's local markdown files.

Scans these folders under Rowan's writing directory:
  - reflections/   (wonders, reflections, research, heartbeats)
  - Journal/       (heartbeats, wonders)
  - research/      (research files)

Detects entry type from filename and H1 heading.
Skips files already imported (matched by file path stored in metadata).
Safe to run multiple times.

Usage:
    python scripts/backfill_journal_files.py
    python scripts/backfill_journal_files.py --dry-run
    python scripts/backfill_journal_files.py --dir "C:\\path\\to\\other\\folder"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

EST = ZoneInfo("America/New_York")

# Default root folder — where Rowan writes files
DEFAULT_ROWAN_DIR = r"C:\Users\user\Documents\Ai Research\Rowan"

# Subfolders to scan (relative to root)
SCAN_SUBDIRS = ["reflections", "Journal", "research"]


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _extract_h1(content: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def _detect_type_from_filename(name: str, folder: str) -> str:
    """Detect entry type from filename stem."""
    n = name.lower()
    # Explicit named patterns
    if re.search(r"wonder", n):
        return "wonder"
    if re.search(r"reflect", n):
        return "reflection"
    if re.search(r"research", n):
        return "research"
    if re.search(r"summary", n):
        return "summary"
    if re.search(r"heartbeat", n):
        return "heartbeat"
    # Folder-based fallback
    if "research" in folder.lower():
        return "research"
    if "reflect" in folder.lower():
        return "heartbeat"
    return "heartbeat"


def _detect_type_from_content(content: str) -> str:
    """Detect entry type from H1 heading or content keywords."""
    h1 = (_extract_h1(content) or "").lower()
    if "wonder" in h1:
        return "wonder"
    if "reflect" in h1:
        return "reflection"
    if "research" in h1:
        return "research"
    if "summary" in h1:
        return "summary"
    # Content keywords
    text = content.lower()[:300]
    if any(w in text for w in ["i wonder", "wondering about", "tonight i am wondering"]):
        return "wonder"
    if any(w in text for w in ["reflecting on", "looking back", "i've been thinking"]):
        return "reflection"
    if any(w in text for w in ["research", "found that", "according to"]):
        return "research"
    return "heartbeat"


def _parse_date_from_filename(stem: str) -> date | None:
    """Try to extract YYYY-MM-DD from filename stem."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", stem)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def _get_local_conn():
    import psycopg
    from psycopg.rows import dict_row
    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("KNOWLEDGE_DATABASE_URL not set in .env")
    return psycopg.connect(url, row_factory=dict_row)


def backfill(rowan_dir: str, dry_run: bool = False) -> None:
    print(f"{'[DRY RUN] ' if dry_run else ''}Backfilling journal from local markdown files...")
    print(f"  Root: {rowan_dir}\n")

    root = Path(rowan_dir)
    if not root.exists():
        raise SystemExit(f"Directory not found: {rowan_dir}")

    # Ensure schema
    if not dry_run:
        from src.agent.journal import ensure_schema
        ensure_schema()

    conn = _get_local_conn()

    # Load already-imported file paths from metadata
    with conn.cursor() as cur:
        cur.execute(
            "SELECT metadata->>'file_path' AS fp FROM journal_entries WHERE metadata->>'file_path' IS NOT NULL"
        )
        already_imported: set[str] = {r["fp"] for r in cur.fetchall() if r["fp"]}

    print(f"  Already imported from files: {len(already_imported)}")

    inserted = 0
    skipped = 0
    errors = 0

    # Collect all .md files from scan subdirs
    files: list[Path] = []
    for subdir in SCAN_SUBDIRS:
        d = root / subdir
        if d.exists():
            files.extend(sorted(d.glob("*.md")))
        else:
            print(f"  (Skipping missing folder: {d})")

    print(f"  Found {len(files)} markdown files\n")

    for fpath in files:
        fp_str = str(fpath)

        if fp_str in already_imported:
            skipped += 1
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as e:
            print(f"  ERROR reading {fpath.name}: {e}")
            errors += 1
            continue

        if not content:
            skipped += 1
            continue

        stem = fpath.stem
        folder = fpath.parent.name

        # Detect type: filename first, then content
        entry_type = _detect_type_from_filename(stem, folder)
        if entry_type == "heartbeat":
            # Try harder from content
            entry_type = _detect_type_from_content(content)

        # Extract title from H1
        title = _extract_h1(content) or stem

        # Parse date from filename, fall back to file mtime
        edate = _parse_date_from_filename(stem)
        if edate is None:
            mtime = fpath.stat().st_mtime
            edate = datetime.fromtimestamp(mtime, tz=EST).date()

        # Use file mtime as created_at for ordering
        mtime = fpath.stat().st_mtime
        created_at = datetime.fromtimestamp(mtime, tz=EST)

        wc = _word_count(content)

        if dry_run:
            print(f"  [DRY] {edate} {entry_type:12s} {wc:5d}w  {fpath.name[:60]}")
            print(f"         title: {title[:70]}")
        else:
            try:
                import psycopg
                from psycopg.types.json import Jsonb
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO journal_entries
                            (entry_date, entry_type, title, content, word_count,
                             source, metadata, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, 'rowan', %s, %s, %s)
                        """,
                        (
                            edate, entry_type, title, content, wc,
                            Jsonb({"file_path": fp_str, "filename": fpath.name}),
                            created_at, created_at,
                        ),
                    )
                already_imported.add(fp_str)
            except Exception as e:
                print(f"  ERROR inserting {fpath.name}: {e}")
                errors += 1
                continue

        inserted += 1

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Inserted : {inserted}")
    print(f"  Skipped  : {skipped}")
    print(f"  Errors   : {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill journal from Rowan's local .md files")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--dir",
        default=DEFAULT_ROWAN_DIR,
        help=f"Root folder to scan (default: {DEFAULT_ROWAN_DIR})",
    )
    args = parser.parse_args()
    backfill(rowan_dir=args.dir, dry_run=args.dry_run)
