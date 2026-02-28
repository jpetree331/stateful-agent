"""
Core memory tools for the agent.

The agent can update, append to, or rollback core memory blocks.
Use these tools carefully; rollback is available if a mistake is made.
"""
from langchain_core.tools import tool

from .core_memory import append_to_block, rollback_block, update_block


@tool
def core_memory_update(block_type: str, content: str) -> str:
    """
    Replace the entire content of a core memory block.

    Use when you need to fully rewrite a block. Prefer core_memory_append when
    adding new information to avoid accidentally removing existing content.

    Args:
        block_type: One of 'user', 'identity', or 'ideaspace'.
        content: The new full content for the block.

    Returns:
        Success message or error.
    """
    ok, msg = update_block(block_type, content)
    return msg if ok else f"Error: {msg}"


@tool
def core_memory_append(block_type: str, addition: str) -> str:
    """
    Append new content to a core memory block.

    Prefer this over core_memory_update when adding information, as it preserves
    existing content and reduces the risk of accidental deletion.

    Args:
        block_type: One of 'user', 'identity', or 'ideaspace'.
        addition: The text to append (will be added after existing content).

    Returns:
        Success message or error.
    """
    ok, msg = append_to_block(block_type, addition)
    return msg if ok else f"Error: {msg}"


@tool
def core_memory_rollback(block_type: str) -> str:
    """
    Restore a core memory block to its previous version.

    Use immediately if you made an editing mistake (wrong content, accidental
    deletion, etc.). Each rollback restores one step back in history.

    Args:
        block_type: One of 'user', 'identity', or 'ideaspace'.

    Returns:
        Success message or error (e.g. if no previous version exists).
    """
    ok, msg = rollback_block(block_type)
    return msg if ok else f"Error: {msg}"
