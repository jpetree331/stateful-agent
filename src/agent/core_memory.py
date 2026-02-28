"""
Core memory blocks: user, identity, ideaspace (editable), system_instructions (read-only).

Always in context. Agent can edit user/identity/ideaspace with care. Rollback available.
"""
from __future__ import annotations

from .db import get_connection


def get_all_blocks() -> dict[str, str]:
    """Load all core memory blocks. Returns {block_type: content}."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT block_type, content FROM core_memory ORDER BY block_type"
            )
            rows = cur.fetchall()
    result = {row["block_type"]: (row["content"] or "") for row in rows}
    # Add read-only system instructions
    result["system_instructions"] = get_system_instructions()
    return result


def get_system_instructions() -> str:
    """Load read-only system instructions. Agent cannot edit."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM system_instructions WHERE id = 1")
            row = cur.fetchone()
    return (row["content"] or "") if row else ""


def update_system_instructions(content: str) -> None:
    """Update system instructions. For import script only; agent has no tool for this."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_instructions (id, content, updated_at)
                VALUES (1, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                """,
                (content,),
            )


def get_block(block_type: str) -> str:
    """Get a single block. Returns empty string if not found."""
    blocks = get_all_blocks()
    return blocks.get(block_type, "")


def update_block(block_type: str, content: str) -> tuple[bool, str]:
    """
    Replace block content. Saves previous version to history for rollback.
    Returns (success, message).
    """
    if block_type not in ("user", "identity", "ideaspace"):
        return False, f"Invalid block_type: {block_type}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, version FROM core_memory WHERE block_type = %s",
                (block_type,),
            )
            row = cur.fetchone()
            if row:
                # Save to history before overwriting
                cur.execute(
                    """
                    INSERT INTO core_memory_history (block_type, content, version, updated_at)
                    SELECT block_type, content, version, updated_at FROM core_memory
                    WHERE block_type = %s
                    """,
                    (block_type,),
                )
                new_version = row["version"] + 1
            else:
                new_version = 1

            cur.execute(
                """
                INSERT INTO core_memory (block_type, content, version, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (block_type) DO UPDATE SET
                    content = EXCLUDED.content,
                    version = EXCLUDED.version,
                    updated_at = NOW()
                """,
                (block_type, content, new_version),
            )

    return True, f"Updated {block_type} (v{new_version})"


def append_to_block(block_type: str, addition: str) -> tuple[bool, str]:
    """
    Append to block. Saves previous version to history.
    Returns (success, message).
    """
    if block_type not in ("user", "identity", "ideaspace"):
        return False, f"Invalid block_type: {block_type}"

    current = get_block(block_type)
    new_content = (current + "\n\n" + addition).strip() if current else addition
    return update_block(block_type, new_content)


def rollback_block(block_type: str) -> tuple[bool, str]:
    """
    Restore block to previous version. Removes the reverted entry from history
    so further rollbacks go further back. Returns (success, message).
    """
    if block_type not in ("user", "identity", "ideaspace"):
        return False, f"Invalid block_type: {block_type}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content, version FROM core_memory_history
                WHERE block_type = %s
                ORDER BY id DESC LIMIT 1
                """,
                (block_type,),
            )
            row = cur.fetchone()
            if not row:
                return False, f"No previous version of {block_type} to rollback to"

            prev_content = row["content"]
            prev_version = row["version"]
            history_id = row["id"]

            # Restore and remove the reverted entry from history
            cur.execute(
                """
                UPDATE core_memory SET content = %s, version = %s, updated_at = NOW()
                WHERE block_type = %s
                """,
                (prev_content, prev_version, block_type),
            )
            cur.execute("DELETE FROM core_memory_history WHERE id = %s", (history_id,))

    return True, f"Rolled back {block_type} to version {prev_version}"
