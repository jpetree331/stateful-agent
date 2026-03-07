#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migrate Railway PostgreSQL to a local PostgreSQL database.

Backs up Railway via pg_dump, creates a new local database, restores it with
pg_restore, verifies row counts, and optionally updates .env to point the agent
at the new local DB.

Usage:
    # Step 1: dry run — just run pre-flight checks (no changes made)
    python scripts/migrate_to_local_postgres.py

    # Step 2: full migration (backup + create DB + restore + verify)
    python scripts/migrate_to_local_postgres.py --run

    # Step 3: switch .env to use local DB (after verifying restore looks good)
    python scripts/migrate_to_local_postgres.py --switch

    # All in one (migrate AND switch if verification passes)
    python scripts/migrate_to_local_postgres.py --run --switch

    # Only verify row counts (Railway vs local, no migration)
    python scripts/migrate_to_local_postgres.py --verify-only

Flags:
    --run           Execute the migration (backup + restore). Without this, only
                    pre-flight checks are performed.
    --switch        Update .env after a successful restore. Comments out the
                    Railway DATABASE_URL and inserts the local one.
    --verify-only   Compare row counts between Railway and local (no migration).
    --db-name NAME  Target database name (default: rowan-agent).
    --skip-backup   Skip the pg_dump safety backup (NOT recommended).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

DATA_DIR = _ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# pg_dump / pg_restore discovery (reuse backup_postgres.py pattern)
# ---------------------------------------------------------------------------

def _find_pg_tool(name: str) -> str | None:
    """Find a PostgreSQL tool (pg_dump, pg_restore, psql, createdb) on PATH or Program Files."""
    exe = shutil.which(name)
    if exe:
        return exe
    for base in [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "PostgreSQL",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "PostgreSQL",
    ]:
        if base.exists():
            for sub in sorted(base.iterdir(), reverse=True):  # prefer newest version
                candidate = sub / "bin" / f"{name}.exe"
                if candidate.exists():
                    return str(candidate)
    return None


# ---------------------------------------------------------------------------
# URL / credential helpers
# ---------------------------------------------------------------------------

def _parse_local_creds(kb_url: str) -> dict:
    """
    Parse host/port/user/password from KNOWLEDGE_DATABASE_URL.
    Returns dict with keys: host, port, user, password, dbname.
    """
    p = urlparse(kb_url)
    return {
        "host": p.hostname or "localhost",
        "port": p.port or 5432,
        "user": p.username or "postgres",
        "password": p.password or "",
        "dbname": (p.path or "/").lstrip("/"),
    }


def _build_local_url(creds: dict, target_db: str) -> str:
    """Build a connection URL for the target local database."""
    pwd = creds["password"]
    if pwd:
        auth = f"{creds['user']}:{pwd}"
    else:
        auth = creds["user"]
    return f"postgresql://{auth}@{creds['host']}:{creds['port']}/{target_db}"


# ---------------------------------------------------------------------------
# Step 0: Pre-flight checks
# ---------------------------------------------------------------------------

def preflight(db_name: str) -> tuple[str, str, dict]:
    """
    Verify env vars, tools, and connectivity.
    Returns (railway_url, local_target_url, local_creds) or raises SystemExit.
    """
    print("\n=== Pre-flight Checks ===\n")

    # 1. Railway DATABASE_URL
    railway_url = os.environ.get("DATABASE_URL", "").strip()
    if not railway_url:
        print("  [FAIL] DATABASE_URL is not set in .env")
        sys.exit(1)
    # Mask password for display
    p = urlparse(railway_url)
    masked = urlunparse(p._replace(netloc=f"{p.username}:***@{p.hostname}:{p.port}"))
    print(f"  [OK]  DATABASE_URL        = {masked}")

    # 2. KNOWLEDGE_DATABASE_URL (source of local Postgres credentials)
    kb_url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not kb_url:
        print("  [FAIL] KNOWLEDGE_DATABASE_URL is not set in .env")
        sys.exit(1)
    p2 = urlparse(kb_url)
    masked2 = urlunparse(p2._replace(netloc=f"{p2.username}:***@{p2.hostname}:{p2.port}"))
    print(f"  [OK]  KNOWLEDGE_DATABASE_URL = {masked2}")

    creds = _parse_local_creds(kb_url)
    local_target_url = _build_local_url(creds, db_name)

    # 3. pg_dump / pg_restore / psql
    for tool in ("pg_dump", "pg_restore", "psql"):
        path = _find_pg_tool(tool)
        if path:
            print(f"  [OK]  {tool:<12} = {path}")
        else:
            print(f"  [FAIL] {tool} not found. Install PostgreSQL client tools:")
            print("         winget install PostgreSQL.PostgreSQL")
            print("         or https://www.postgresql.org/download/windows/")
            sys.exit(1)

    # 4. Railway connectivity
    print("\n  Testing Railway connection...")
    try:
        import psycopg
        with psycopg.connect(railway_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                ver = cur.fetchone()[0][:60]
        print(f"  [OK]  Railway connected: {ver}")
    except Exception as e:
        print(f"  [FAIL] Cannot connect to Railway: {e}")
        sys.exit(1)

    # 5. Local Postgres connectivity (maintenance DB)
    print("\n  Testing local Postgres connection...")
    maintenance_url = _build_local_url(creds, "postgres")
    try:
        import psycopg
        with psycopg.connect(maintenance_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                ver = cur.fetchone()[0][:60]
        print(f"  [OK]  Local Postgres:   {ver}")
    except Exception as e:
        print(f"  [FAIL] Cannot connect to local Postgres: {e}")
        print(f"         Tried: {maintenance_url.replace(creds.get('password',''), '***')}")
        sys.exit(1)

    print("\n  All pre-flight checks passed.\n")
    return railway_url, local_target_url, creds


# ---------------------------------------------------------------------------
# Step 1: Backup Railway DB
# ---------------------------------------------------------------------------

def backup_railway(railway_url: str) -> Path:
    """pg_dump Railway to data/migration_backup_<timestamp>.dump. Exits on failure."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = DATA_DIR / f"migration_backup_{timestamp}.dump"

    pg_dump = _find_pg_tool("pg_dump")
    print(f"\n=== Step 1: Backup Railway DB ===\n")
    print(f"  Output: {backup_path}")

    result = subprocess.run(
        [pg_dump, railway_url, "-Fc", "-f", str(backup_path)],
        capture_output=True,
        text=True,
        timeout=900,  # 15 min
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        print(f"\n  [FAIL] pg_dump failed:")
        print(result.stderr or result.stdout)
        print("\n  Aborting — backup must succeed before migration can proceed.")
        sys.exit(1)

    size_mb = backup_path.stat().st_size / (1024 * 1024)
    print(f"  [OK]  Backup complete: {backup_path.name} ({size_mb:.2f} MB)")
    print(f"\n  Keep this file safe! You can restore Railway at any time with:")
    print(f"  pg_restore -d <RAILWAY_URL> -Fc --no-owner --no-acl {backup_path}\n")

    return backup_path


# ---------------------------------------------------------------------------
# Step 2: Create local database
# ---------------------------------------------------------------------------

def create_local_db(creds: dict, db_name: str) -> None:
    """Create the target database locally. Skips if already exists."""
    print(f"\n=== Step 2: Create Local Database '{db_name}' ===\n")

    import psycopg
    from psycopg import sql

    maintenance_url = _build_local_url(creds, "postgres")
    try:
        # Must use autocommit for CREATE DATABASE
        conn = psycopg.connect(maintenance_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            # Check if it already exists
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,),
            )
            if cur.fetchone():
                print(f"  Database '{db_name}' already exists — skipping create.")
            else:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                print(f"  [OK]  Created database '{db_name}'.")
        conn.close()
    except Exception as e:
        print(f"  [FAIL] Could not create database '{db_name}': {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Step 3: Restore
# ---------------------------------------------------------------------------

def restore_to_local(backup_path: Path, local_target_url: str) -> None:
    """pg_restore the backup into the local database."""
    print(f"\n=== Step 3: Restore to Local Database ===\n")
    print(f"  From: {backup_path.name}")
    p = urlparse(local_target_url)
    masked = f"postgresql://{p.username}:***@{p.hostname}:{p.port}/{p.path.lstrip('/')}"
    print(f"  To:   {masked}\n")

    pg_restore = _find_pg_tool("pg_restore")

    result = subprocess.run(
        [
            pg_restore,
            "-d", local_target_url,
            "-Fc",
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            str(backup_path),
        ],
        capture_output=False,   # stream stderr so user sees progress
        timeout=900,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        print(f"\n  [FAIL] pg_restore exited with code {result.returncode}")
        print("  Check the output above for details.")
        sys.exit(1)

    print("\n  [OK]  Restore complete.")


# ---------------------------------------------------------------------------
# Step 4: Verify row counts
# ---------------------------------------------------------------------------

KEY_TABLES = [
    ("public", "messages"),
    ("public", "core_memory"),
    ("public", "core_memory_history"),
    ("public", "cron_jobs"),
    ("public", "daily_summaries"),
    ("archival", "facts"),
]


def _count_rows(url: str, schema: str, table: str) -> int | str:
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
                return cur.fetchone()[0]
    except Exception as e:
        return f"ERR: {e}"


def verify_counts(railway_url: str, local_target_url: str) -> bool:
    """Compare row counts on key tables. Returns True if all match."""
    print("\n=== Step 4: Verify Row Counts ===\n")
    print(f"  {'Table':<35} {'Railway':>10}  {'Local':>10}  {'Match':>6}")
    print("  " + "-" * 65)

    all_match = True
    for schema, table in KEY_TABLES:
        label = f"{schema}.{table}"
        r_count = _count_rows(railway_url, schema, table)
        l_count = _count_rows(local_target_url, schema, table)

        match = r_count == l_count
        if not match:
            all_match = False
        tick = "[OK]" if match else "[!!]"
        print(f"  {label:<35} {str(r_count):>10}  {str(l_count):>10}  {tick:>6}")

    print()
    if all_match:
        print("  [OK]  All counts match. Migration looks complete.")
    else:
        print("  [!!]  Some counts differ. Review before switching .env.")
        print("        This can happen if Railway has new data written after the backup started.")
        print("        If the agent was running during migration, differences are expected.")

    return all_match


# ---------------------------------------------------------------------------
# Step 5: Switch .env
# ---------------------------------------------------------------------------

def switch_env(creds: dict, db_name: str) -> None:
    """
    Update .env in-place:
      - Comment out current DATABASE_URL line (prefix with '# [pre-migration] ')
      - Insert new DATABASE_URL pointing to local rowan-agent DB
    """
    print("\n=== Step 5: Update .env ===\n")

    env_path = _ROOT / ".env"
    if not env_path.exists():
        print("  [FAIL] .env not found at", env_path)
        sys.exit(1)

    local_url = _build_local_url(creds, db_name)
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)

    new_lines = []
    inserted = False
    already_local = False

    for line in lines:
        stripped = line.rstrip("\n").rstrip("\r")

        # Skip lines that are already our migration marker
        if stripped.startswith("# [pre-migration] DATABASE_URL="):
            new_lines.append(line)
            continue

        # Active DATABASE_URL line
        if re.match(r"^DATABASE_URL\s*=", stripped):
            if local_url in stripped:
                # Already pointing local — nothing to do
                already_local = True
                new_lines.append(line)
                continue

            # Comment it out
            new_lines.append(f"# [pre-migration] {stripped}\n")
            # Insert the local URL right after
            new_lines.append(f"DATABASE_URL={local_url}\n")
            inserted = True
            continue

        new_lines.append(line)

    if already_local:
        print(f"  .env already points to local database '{db_name}'. No change needed.")
        return

    if not inserted:
        # DATABASE_URL wasn't found — append it
        new_lines.append(f"\nDATABASE_URL={local_url}\n")
        print(f"  DATABASE_URL not found in .env — appended local URL.")
        inserted = True

    env_path.write_text("".join(new_lines), encoding="utf-8")

    # Mask password for display
    p = urlparse(local_url)
    masked = f"postgresql://{p.username}:***@{p.hostname}:{p.port}/{p.path.lstrip('/')}"
    print(f"  [OK]  DATABASE_URL updated -> {masked}")
    print()
    print("  To roll back, open .env and:")
    print("    1. Delete the new DATABASE_URL line")
    print("    2. Remove '# [pre-migration] ' from the old Railway line")
    print("    3. Restart the agent/API\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Migrate Railway PostgreSQL to a local PostgreSQL database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--run",          action="store_true", help="Execute the migration (backup + restore)")
    p.add_argument("--switch",       action="store_true", help="Update .env to use local DB after migration")
    p.add_argument("--verify-only",  action="store_true", help="Only compare row counts (no migration)")
    p.add_argument("--db-name",      default="rowan-agent", help="Target database name (default: rowan-agent)")
    p.add_argument("--skip-backup",  action="store_true", help="Skip pg_dump safety backup (NOT recommended)")
    args = p.parse_args()

    db_name = args.db_name

    # Always run pre-flight
    railway_url, local_target_url, creds = preflight(db_name)

    # --verify-only: just compare counts
    if args.verify_only:
        verify_counts(railway_url, local_target_url)
        return

    # --switch standalone (migration already done, just update .env)
    if args.switch and not args.run:
        switch_env(creds, db_name)
        return

    # Without --run, just show what would happen
    if not args.run:
        print("Pre-flight checks passed.\n")
        print("To run the migration:  python scripts/migrate_to_local_postgres.py --run")
        print("To also switch .env:   python scripts/migrate_to_local_postgres.py --run --switch")
        print("To switch .env only:   python scripts/migrate_to_local_postgres.py --switch")
        return

    # --- Migration ---

    # Step 1: Backup (required safety gate)
    if args.skip_backup:
        print("\n  [WARNING] Skipping backup (--skip-backup). Proceeding without safety net.")
        backup_path = None
    else:
        backup_path = backup_railway(railway_url)

    # Step 2: Create local DB
    create_local_db(creds, db_name)

    # Step 3: Restore
    if backup_path is None:
        print("\n  [SKIP] No backup file — cannot restore. Run without --skip-backup.")
        sys.exit(1)
    restore_to_local(backup_path, local_target_url)

    # Step 4: Verify
    counts_ok = verify_counts(railway_url, local_target_url)

    # Step 5: Switch .env (if requested and verification passed — or user forced it)
    if args.switch:
        if counts_ok:
            switch_env(creds, db_name)
        else:
            print("\n  [!!]  Row count mismatch — .env NOT updated automatically.")
            print("  If you're satisfied the data is correct, run:")
            print(f"  python scripts/migrate_to_local_postgres.py --switch\n")
            sys.exit(1)
    else:
        if counts_ok:
            print("\nMigration complete! To point the agent at the local DB, run:")
            print("  python scripts/migrate_to_local_postgres.py --switch\n")

    print("Done.\n")


if __name__ == "__main__":
    main()
