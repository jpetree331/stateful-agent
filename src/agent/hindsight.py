"""
Hindsight integration: deep memory that learns.

Retains every user/assistant exchange as lived experience.
Agent can recall and reflect via tools.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

HINDSIGHT_BASE_URL = os.environ.get("HINDSIGHT_BASE_URL", "http://localhost:8888")
HINDSIGHT_BANK_ID = os.environ.get("HINDSIGHT_BANK_ID", "stateful-agent")
HINDSIGHT_ENABLED = os.environ.get("HINDSIGHT_ENABLED", "true").lower() in ("true", "1", "yes")
# User ID tag for Hindsight memory (e.g. user:your_id_here). Used when retaining.
HINDSIGHT_USER_ID = os.environ.get("HINDSIGHT_USER_ID", "").strip()


def _get_client():
    """Lazy-import and create Hindsight client."""
    try:
        from hindsight_client import Hindsight
        return Hindsight(base_url=HINDSIGHT_BASE_URL)
    except ImportError:
        return None


def _format_as_lived_experience(user_content: str, assistant_content: str | None) -> str:
    """
    Format a user/assistant exchange as the AI's lived experience.
    Not bullet points — narrative, first-person, experiential.
    """
    user_content = (user_content or "").strip()
    assistant_content = (assistant_content or "").strip() if assistant_content else None

    if assistant_content:
        return (
            f"The user and I were in conversation. They said to me: \"{user_content}\" "
            f"I responded from our shared context: \"{assistant_content}\""
        )
    return f"The user reached out to me. They said: \"{user_content}\""


def retain_exchange(
    bank_id: str,
    user_content: str,
    assistant_content: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    channel_type: str | None = None,
    is_group_chat: bool = False,
) -> bool:
    """
    Retain a user/assistant exchange into Hindsight as lived experience.
    Returns True if retained, False if Hindsight unavailable or disabled.

    Tags applied:
    - user:{user_id} - Stable identity (discord_id, telegram_id, or local_name)
    - channel:{discord|telegram|local} - Platform/source identifier
    - group - Applied if is_group_chat is True
    """
    if not HINDSIGHT_ENABLED:
        return False

    client = _get_client()
    if not client:
        return False

    content = _format_as_lived_experience(user_content, assistant_content)
    effective_bank = bank_id or HINDSIGHT_BANK_ID

    try:
        metadata: dict[str, Any] = {}
        if thread_id:
            metadata["thread_id"] = thread_id

        # Build tags for cross-platform continuity
        tags: list[str] = []

        # Primary user identity tag (prefer passed user_id, fallback to env)
        effective_user_id = (user_id or HINDSIGHT_USER_ID).strip()
        if effective_user_id:
            # Ensure consistent format: user:{id}
            user_tag = effective_user_id if ":" in effective_user_id else f"user:{effective_user_id}"
            tags.append(user_tag)

        # Channel/platform tag
        if channel_type:
            tags.append(f"channel:{channel_type.lower()}")

        # Group chat tag
        if is_group_chat:
            tags.append("group")

        with client:
            client.retain(
                bank_id=effective_bank,
                content=content,
                context="conversation",
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata=metadata if metadata else None,
                tags=tags if tags else None,
            )
        return True
    except Exception:
        return False


def recall(bank_id: str, query: str) -> str:
    """
    Recall memories from Hindsight. Returns formatted string of relevant memories.
    When Hindsight returns results, format them as lived experience — not bullet points.
    """
    client = _get_client()
    if not client:
        return "Hindsight is not available. Memory recall failed."

    effective_bank = bank_id or HINDSIGHT_BANK_ID

    try:
        with client:
            response = client.recall(bank_id=effective_bank, query=query)
        results = getattr(response, "results", []) or []
        if not results:
            return "I don't have any memories that match that."

        # Format as lived recollection — narrative, not bullet list
        texts = []
        for r in results:
            text = getattr(r, "text", None) or (str(r) if r else None)
            if text and isinstance(text, str) and text.strip():
                texts.append(text.strip())

        if not texts:
            return "I don't have any memories that match that."

        return "From my experience with the user:\n\n" + "\n\n".join(texts)
    except Exception as e:
        return f"Hindsight recall failed: {e}"


def reflect(bank_id: str, query: str) -> str:
    """
    Reflect on memories — deeper synthesis, patterns, insights.
    Use for relational questions, pattern-based questions, or self-reflection.
    """
    client = _get_client()
    if not client:
        return "Hindsight is not available. Reflection failed."

    effective_bank = bank_id or HINDSIGHT_BANK_ID

    try:
        with client:
            answer = client.reflect(bank_id=effective_bank, query=query)
        text = getattr(answer, "text", None) or (str(answer) if answer else None)
        return (text or "").strip() or "I reflected but have nothing specific to share."
    except Exception as e:
        return f"Hindsight reflect failed: {e}"
