#!/usr/bin/env python3
"""
Verify Knowledge Bank setup: KNOWLEDGE_DATABASE_URL, pgvector extension, tables.
Run: python -m scripts.check_knowledge_db
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


def main():
    import os

    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not url:
        print("KNOWLEDGE_DATABASE_URL is not set in .env")
        print("Add to .env: KNOWLEDGE_DATABASE_URL=postgresql://user:pass@localhost:5432/rowan-data")
        print("Then run: python -m scripts.setup_knowledge_db")
        sys.exit(1)

    try:
        from src.agent.knowledge_bank import _get_connection, _ensure_schema, list_files
    except ImportError as e:
        print(f"Import error: {e}")
        print("Run: pip install pgvector tiktoken")
        sys.exit(1)

    try:
        conn = _get_connection()
        _ensure_schema(conn)
        files = list_files()
        conn.close()
        print(f"Knowledge Bank OK. {len(files)} file(s) stored.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
