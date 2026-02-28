"""
Telegram tools: send messages, images, and read incoming messages via the Telegram Bot API.

No library needed — uses httpx (already installed). Works with any Telegram bot.

Configuration (.env):
  TELEGRAM_BOT_TOKEN    — token from @BotFather (format: 123456789:ABCdef...)
  TELEGRAM_CHAT_ID      — optional default chat/group ID for outbound messages

Getting your chat ID:
  1. Send any message to your bot
  2. Call telegram_read_messages() — it will show the chat_id in each message
  3. Set TELEGRAM_CHAT_ID in .env for convenience

Telegram Bot API docs: https://core.telegram.org/bots/api
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from langchain_core.tools import tool

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_DEFAULT_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Tracks the last processed update ID so read_messages doesn't return duplicates.
_OFFSET_PATH = Path(__file__).resolve().parents[2] / "data" / "telegram_offset.txt"

_TIMEOUT = 15


def _base_url() -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _require_token() -> str | None:
    if not TELEGRAM_BOT_TOKEN:
        return (
            "Error: TELEGRAM_BOT_TOKEN not configured in .env. "
            "Create a bot with @BotFather and paste the token."
        )
    return None


def _load_offset() -> int:
    try:
        return int(_OFFSET_PATH.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    try:
        _OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OFFSET_PATH.write_text(str(offset))
    except Exception:
        pass


@tool
def telegram_send_message(text: str, chat_id: str = "", parse_mode: str = "Markdown") -> str:
    """
    Send a text message to a Telegram chat via the bot.

    Use to notify the user on their phone, send updates, or communicate via Telegram.
    Supports Markdown formatting (bold with **text**, code with `code`, etc.).

    Args:
        text: The message to send. Supports Telegram Markdown:
              *bold*, _italic_, `code`, ```code block```, [link text](URL)
        chat_id: Telegram chat ID (user, group, or channel). Leave blank
                 to use TELEGRAM_CHAT_ID from .env.
        parse_mode: "Markdown" (default) or "HTML" or "" for plain text.
    """
    err = _require_token()
    if err:
        return err

    cid = chat_id.strip() or TELEGRAM_DEFAULT_CHAT_ID
    if not cid:
        return "Error: provide a chat_id or set TELEGRAM_CHAT_ID in .env."

    payload: dict = {"chat_id": cid, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = httpx.post(
            f"{_base_url()}/sendMessage",
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            msg_id = result["result"]["message_id"]
            return f"Message sent to Telegram chat {cid} (message_id: {msg_id})."
        return f"Telegram error: {result.get('description', 'unknown')}"
    except httpx.HTTPStatusError as e:
        return f"Telegram API error {e.response.status_code}: {e.response.text[:300]}"
    except Exception as e:
        return f"Telegram send failed: {e}"


@tool
def telegram_send_image(image_path: str, chat_id: str = "", caption: str = "") -> str:
    """
    Send an image file to a Telegram chat.

    Useful for forwarding screenshots or charts directly to the user's phone.
    Combine with analyze_screenshot(save=True) to capture the screen and send it.

    Args:
        image_path: Absolute or relative path to the image file (PNG, JPEG, etc.).
        chat_id: Telegram chat ID. Leave blank for TELEGRAM_CHAT_ID from .env.
        caption: Optional caption to display under the image.
    """
    err = _require_token()
    if err:
        return err

    cid = chat_id.strip() or TELEGRAM_DEFAULT_CHAT_ID
    if not cid:
        return "Error: provide a chat_id or set TELEGRAM_CHAT_ID in .env."

    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        return f"Error: image file not found: {path}"

    try:
        with open(path, "rb") as f:
            files = {"photo": (path.name, f, "image/png")}
            data = {"chat_id": cid}
            if caption:
                data["caption"] = caption
            resp = httpx.post(
                f"{_base_url()}/sendPhoto",
                files=files,
                data=data,
                timeout=30,  # larger timeout for file upload
            )
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            msg_id = result["result"]["message_id"]
            return f"Image sent to Telegram chat {cid} (message_id: {msg_id})."
        return f"Telegram error: {result.get('description', 'unknown')}"
    except httpx.HTTPStatusError as e:
        return f"Telegram API error {e.response.status_code}: {e.response.text[:300]}"
    except Exception as e:
        return f"Telegram send image failed: {e}"


@tool
def telegram_read_messages(limit: int = 10, mark_as_read: bool = True) -> str:
    """
    Read recent incoming messages sent to the bot.

    Fetches updates using Telegram's getUpdates API. By default, marks messages
    as read so they won't appear again next time (uses a persisted offset).
    Shows the chat_id for each message — use it to reply with telegram_send_message.

    Args:
        limit: Max messages to return (default 10, max 100).
        mark_as_read: If True (default), advance the offset so these messages
                      won't show again. Set False to re-read without consuming.
    """
    err = _require_token()
    if err:
        return err

    offset = _load_offset()
    limit = min(int(limit), 100)

    try:
        params: dict = {"limit": limit, "timeout": 0}
        if offset:
            params["offset"] = offset

        resp = httpx.get(
            f"{_base_url()}/getUpdates",
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as e:
        return f"Telegram API error {e.response.status_code}: {e.response.text[:300]}"
    except Exception as e:
        return f"Telegram read failed: {e}"

    if not result.get("ok"):
        return f"Telegram error: {result.get('description', 'unknown')}"

    updates = result.get("result", [])

    if not updates:
        return "No new messages."

    lines = [f"=== Telegram Messages ({len(updates)} update(s)) ===\n"]
    max_update_id = 0

    for update in updates:
        update_id = update.get("update_id", 0)
        if update_id > max_update_id:
            max_update_id = update_id

        # Handle different update types
        msg = update.get("message") or update.get("channel_post") or update.get("edited_message")
        if not msg:
            # Other update types (callbacks, etc.) — summarise
            lines.append(f"[update_id {update_id}] Non-message update: {list(update.keys())}")
            continue

        chat = msg.get("chat", {})
        chat_id = chat.get("id", "?")
        chat_name = (
            chat.get("title")
            or chat.get("username")
            or f"{chat.get('first_name', '')} {chat.get('last_name', '')}".strip()
            or str(chat_id)
        )
        sender = msg.get("from", {})
        sender_name = (
            sender.get("username")
            or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
            or "unknown"
        )
        text = msg.get("text") or msg.get("caption") or ""
        date = msg.get("date", 0)

        # Format timestamp
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(date, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if date else "?"

        # Note attachments
        extras = []
        for key in ("photo", "document", "sticker", "audio", "video", "voice"):
            if key in msg:
                extras.append(key)
        if extras:
            text = f"[{', '.join(extras)}] {text}".strip()
        if not text:
            text = "[no text]"

        lines.append(
            f"[{ts}] chat_id={chat_id} ({chat_name}) | from: {sender_name}\n"
            f"  {text}"
        )

    if mark_as_read and max_update_id > 0:
        _save_offset(max_update_id + 1)
        lines.append(f"\n(Marked as read. Offset advanced to {max_update_id + 1}.)")

    return "\n".join(lines)


@tool
def telegram_bot_info() -> str:
    """
    Get information about the connected Telegram bot (name, username, ID).

    Useful for confirming the bot is configured correctly and seeing which
    bot the agent is operating as.
    """
    err = _require_token()
    if err:
        return err

    try:
        resp = httpx.get(f"{_base_url()}/getMe", timeout=_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        return f"Telegram getMe failed: {e}"

    if not result.get("ok"):
        return f"Telegram error: {result.get('description', 'unknown')}"

    bot = result["result"]
    return (
        f"Telegram Bot Info:\n"
        f"  Name:     {bot.get('first_name', '?')}\n"
        f"  Username: @{bot.get('username', '?')}\n"
        f"  ID:       {bot.get('id', '?')}\n"
        f"  Can join groups: {bot.get('can_join_groups', '?')}\n"
        f"  Supports inline: {bot.get('supports_inline_queries', '?')}"
    )
