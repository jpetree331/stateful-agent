"""
Import core memory block contents from text files.

Usage:
    python scripts/import_core_memory.py --path /path/to/memory/files

Expected files in the directory:
    IDENTITY.txt, USER.txt, IDEASPACE.txt, NEWSYSINSTRUCT.txt
"""
from __future__ import annotations

import argparse

from dotenv import load_dotenv
load_dotenv()
import re
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.db import setup_schema
from src.agent.core_memory import update_block, update_system_instructions


DEFAULT_PATH = None  # No default — use --path argument when running this script

BLOCK_FILES = {
    "identity": "IDENTITY.txt",
    "user": "USER.txt",
    "ideaspace": "IDEASPACE.txt",
}

# Read-only system instructions (agent cannot edit; imported separately)
SYSTEM_INSTRUCTIONS_FILE = "NEWSYSINSTRUCT.txt"


def clean_content(text: str) -> str:
    """
    Clean markdown content for core memory storage.
    - Strip BOM and leading/trailing whitespace
    - Remove YAML frontmatter blocks (--- ... ---)
    - Normalize excessive blank lines (max 2 between sections)
    """
    text = text.lstrip("\ufeff").strip()
    # Remove YAML frontmatter (--- ... ---), including multi-block
    while re.search(r"^---\s*\n.*?\n---\s*\n*", text, flags=re.DOTALL):
        text = re.sub(r"^---\s*\n.*?\n---\s*\n*", "", text, count=1, flags=re.DOTALL)
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description="Import core memory from text files")
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Directory containing IDENTITY.txt, USER.txt, IDEASPACE.txt, NEWSYSINSTRUCT.txt",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print content without importing")
    args = parser.parse_args()

    setup_schema()

    for block_type, filename in BLOCK_FILES.items():
        filepath = args.path / filename
        if not filepath.exists():
            print(f"SKIP: {filepath} not found")
            continue

        content = filepath.read_text(encoding="utf-8")
        content = clean_content(content)

        if args.dry_run:
            print(f"\n--- {block_type.upper()} (first 300 chars) ---")
            print(content[:300] + "..." if len(content) > 300 else content)
            continue

        ok, msg = update_block(block_type, content)
        if ok:
            print(f"OK: {msg}")
        else:
            print(f"ERROR: {msg}")

    # Import read-only system instructions
    sys_path = args.path / SYSTEM_INSTRUCTIONS_FILE
    if sys_path.exists():
        content = sys_path.read_text(encoding="utf-8")
        content = clean_content(content)
        if args.dry_run:
            print(f"\n--- SYSTEM_INSTRUCTIONS (first 300 chars) ---")
            print(content[:300] + "..." if len(content) > 300 else content)
        else:
            update_system_instructions(content)
            print(f"OK: Updated system_instructions (read-only)")
    else:
        print(f"SKIP: {sys_path} not found (system instructions)")


if __name__ == "__main__":
    main()
