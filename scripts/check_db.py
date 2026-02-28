#!/usr/bin/env python3
"""Quick script to verify messages are in Postgres. Run: python -m scripts.check_db"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from src.agent.db import get_connection

def main():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT thread_id, idx, role, LEFT(content, 100) as content_preview, created_at
                   FROM messages ORDER BY created_at DESC LIMIT 10"""
            )
            rows = cur.fetchall()
    print("Latest 10 messages in DB:")
    for r in rows:
        prev = (r["content_preview"] or "")[:80]
        print(f"  {r['created_at']} | {r['thread_id']} | idx={r['idx']} | {r['role']}: {repr(prev)}...")
    print("\n✓ Database check complete.")

if __name__ == "__main__":
    main()
