"""
Discord tools: send and read messages via the Discord REST API.

Uses your existing Discord bot token — no library needed, just httpx (already installed).
The bot must be invited to any server/channel you want to interact with.

Configuration (.env):
  DISCORD_BOT_TOKEN   — your bot token from https://discord.com/developers/applications
  DISCORD_CHANNEL_ID  — optional default channel ID (saves specifying it every call)

Getting channel/guild IDs: Enable Developer Mode in Discord settings (App Settings →
Advanced → Developer Mode), then right-click any channel or server and click "Copy ID".
"""
from __future__ import annotations

import os

import httpx
from langchain_core.tools import tool

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_DEFAULT_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")

_BASE = "https://discord.com/api/v10"
_TIMEOUT = 15


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "LangGraphAgent/1.0",
    }


def _require_token() -> str | None:
    """Return error string if token is missing, else None."""
    if not DISCORD_BOT_TOKEN:
        return (
            "Error: DISCORD_BOT_TOKEN not configured in .env. "
            "Get your token from https://discord.com/developers/applications"
        )
    return None


@tool
def discord_send_message(content: str, channel_id: str = "") -> str:
    """
    Send a message to a Discord channel via the bot.

    Use to notify the user on Discord, post updates to a server channel, or
    send the agent's output somewhere they'll see it outside the dashboard.

    Args:
        content: The message text to send (supports Discord markdown).
        channel_id: The Discord channel ID to send to.
                    Leave blank to use the default DISCORD_CHANNEL_ID from .env.
    """
    err = _require_token()
    if err:
        return err

    cid = channel_id.strip() or DISCORD_DEFAULT_CHANNEL_ID
    if not cid:
        return "Error: provide a channel_id or set DISCORD_CHANNEL_ID in .env."

    try:
        resp = httpx.post(
            f"{_BASE}/channels/{cid}/messages",
            json={"content": content},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        msg = resp.json()
        return f"Message sent to channel {cid} (message ID: {msg.get('id', '?')})."
    except httpx.HTTPStatusError as e:
        return f"Discord API error {e.response.status_code}: {e.response.text[:300]}"
    except Exception as e:
        return f"Discord send failed: {e}"


@tool
def discord_read_messages(channel_id: str = "", limit: int = 10) -> str:
    """
    Read recent messages from a Discord channel.

    Use to check what's been said in a channel, catch up on a conversation,
    or read incoming messages from the user on Discord.

    Args:
        channel_id: The channel to read from. Leave blank for DISCORD_CHANNEL_ID from .env.
        limit: Number of recent messages to fetch (default 10, max 50).
    """
    err = _require_token()
    if err:
        return err

    cid = channel_id.strip() or DISCORD_DEFAULT_CHANNEL_ID
    if not cid:
        return "Error: provide a channel_id or set DISCORD_CHANNEL_ID in .env."

    limit = min(int(limit), 50)

    try:
        resp = httpx.get(
            f"{_BASE}/channels/{cid}/messages",
            params={"limit": limit},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        messages = resp.json()
    except httpx.HTTPStatusError as e:
        return f"Discord API error {e.response.status_code}: {e.response.text[:300]}"
    except Exception as e:
        return f"Discord read failed: {e}"

    if not messages:
        return f"No messages found in channel {cid}."

    # Discord returns newest first — reverse so oldest is at top
    messages = list(reversed(messages))

    lines = [f"=== Discord Messages (channel {cid}) ===\n"]
    for msg in messages:
        author = msg.get("author", {})
        username = author.get("global_name") or author.get("username", "unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")[:16].replace("T", " ")
        is_bot = author.get("bot", False)
        label = f"{username} (bot)" if is_bot else username

        # Include attachment/embed info if no text content
        if not content:
            attachments = msg.get("attachments", [])
            embeds = msg.get("embeds", [])
            if attachments:
                content = f"[{len(attachments)} attachment(s)]"
            elif embeds:
                content = f"[embed: {embeds[0].get('title', 'no title')}]"
            else:
                content = "[no text content]"

        lines.append(f"[{timestamp}] {label}: {content}")

    return "\n".join(lines)


@tool
def discord_get_channel_info(channel_id: str = "") -> str:
    """
    Get information about a Discord channel (name, topic, server, type).

    Useful for confirming the right channel ID before sending, or for
    discovering what server/guild a channel belongs to.

    Args:
        channel_id: The channel ID to look up. Leave blank for DISCORD_CHANNEL_ID from .env.
    """
    err = _require_token()
    if err:
        return err

    cid = channel_id.strip() or DISCORD_DEFAULT_CHANNEL_ID
    if not cid:
        return "Error: provide a channel_id or set DISCORD_CHANNEL_ID in .env."

    try:
        resp = httpx.get(
            f"{_BASE}/channels/{cid}",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        ch = resp.json()
    except httpx.HTTPStatusError as e:
        return f"Discord API error {e.response.status_code}: {e.response.text[:300]}"
    except Exception as e:
        return f"Discord channel lookup failed: {e}"

    channel_types = {
        0: "Text channel", 1: "DM", 2: "Voice", 3: "Group DM",
        4: "Category", 5: "Announcement", 10: "Thread", 11: "Thread",
        12: "Thread", 13: "Stage", 15: "Forum",
    }
    ch_type = channel_types.get(ch.get("type", -1), f"type {ch.get('type')}")

    lines = [
        f"Channel ID: {cid}",
        f"Name: {ch.get('name', 'N/A')} ({ch_type})",
    ]
    if ch.get("topic"):
        lines.append(f"Topic: {ch['topic']}")
    if ch.get("guild_id"):
        lines.append(f"Server (guild) ID: {ch['guild_id']}")

    return "\n".join(lines)
