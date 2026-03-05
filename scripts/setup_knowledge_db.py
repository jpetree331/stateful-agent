#!/usr/bin/env python3
"""
Create the Knowledge Bank database and enable pgvector. No psql/createdb needed.
Run: python -m scripts.setup_knowledge_db

Requires: KNOWLEDGE_DATABASE_URL in .env (e.g. postgresql://postgres:password@localhost:5432/agent-data)
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


def main():
    import os
    from urllib.parse import urlparse, urlunparse

    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not url:
        print("KNOWLEDGE_DATABASE_URL is not set in .env")
        sys.exit(1)

    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    db_name = path_parts[0] if path_parts else "agent-data"

    # Connect to 'postgres' to create the target DB
    base_path = "/postgres" if parsed.path else "/postgres"
    admin_url = urlunparse(parsed._replace(path=base_path))

    try:
        import psycopg
    except ImportError:
        print("Run: pip install psycopg[binary]")
        sys.exit(1)

    print(f"Creating database '{db_name}'...")
    try:
        conn = psycopg.connect(admin_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,),
            )
            if cur.fetchone():
                print(f"  Database '{db_name}' already exists.")
            else:
                cur.execute(f'CREATE DATABASE "{db_name}"')
                print(f"  Created '{db_name}'.")
        conn.close()
    except Exception as e:
        print(f"  Failed: {e}")
        print("  Make sure PostgreSQL is running and credentials in .env are correct.")
        sys.exit(1)

    print("Enabling pgvector extension...")
    try:
        conn = psycopg.connect(url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.close()
        print("  Done.")
    except Exception as e:
        print(f"  Failed: {e}")
        print("  Install pgvector: https://github.com/pgvector/pgvector#installation")
        sys.exit(1)

    print("\nKnowledge Bank database ready. Run: python -m scripts.check_knowledge_db")


if __name__ == "__main__":
    main()
