"""
Telegram inbound listener — long-polls getUpdates so the agent responds immediately
when the user sends a message, without burning CPU on short-interval polling.

How it works:
  - On startup, verifies the bot token via getMe and logs the bot username.
  - Fetches any pending updates once (timeout=0) and advances past them so old
    messages are never replayed after a restart.
  - Long-polls getUpdates with timeout=30: Telegram holds the connection open
    up to 30 seconds waiting for a new message, then returns immediately.
  - Filters to TELEGRAM_CHAT_ID. All other chats and bot messages are ignored.
  - Responses are sent back via sendMessage.
  - Long responses are split at 4096 chars (Telegram limit).

Required .env variables:
  TELEGRAM_BOT_TOKEN  — bot token from @BotFather
  TELEGRAM_CHAT_ID    — your personal chat ID with the bot
    To find it: message @userinfobot on Telegram, it replies with your ID.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger("telegram.listener")

_BASE = "https://api.telegram.org"
_LONG_POLL_TIMEOUT = 30  # seconds Telegram holds the connection waiting for updates

_task: asyncio.Task | None = None


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def _get_me() -> dict | None:
    """Verify the bot token and return bot info dict, or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_BASE}/bot{_token()}/getMe")
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data["result"]
        logger.error(f"Telegram getMe failed {resp.status_code}: {resp.text[:300]}")
        return None
    except Exception as e:
        logger.error(f"Telegram getMe error: {e}")
        return None


async def _get_updates(offset: int | None, timeout: int) -> list[dict]:
    params: dict = {"timeout": timeout, "limit": 100, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    try:
        # httpx timeout must be > Telegram's long-poll timeout to avoid premature cutoff
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            resp = await client.get(
                f"{_BASE}/bot{_token()}/getUpdates",
                params=params,
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        if resp.status_code == 409:
            logger.error(
                "Telegram 409 Conflict: another getUpdates call is already running "
                "(e.g. another process, or telegram_read_messages tool was called). "
                "Only one poller can run at a time. Backing off 10s."
            )
        else:
            logger.warning(f"Telegram getUpdates {resp.status_code}: {resp.text[:300]}")
        return []
    except httpx.ReadTimeout:
        # Can happen if Telegram holds the connection slightly longer than our timeout buffer
        return []
    except Exception as e:
        logger.warning(f"Telegram getUpdates error: {e}")
        return []


async def _send_message(chat_id: int, text: str) -> None:
    """Send a message, splitting at 4096-char chunks (Telegram limit)."""
    chunks = [text[i : i + 4096] for i in range(0, len(text), 4096)]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for chunk in chunks:
                resp = await client.post(
                    f"{_BASE}/bot{_token()}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                )
                if resp.status_code not in (200, 201):
                    logger.warning(f"Telegram send {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


async def _poll_loop(agent, target_chat_id: int) -> None:
    # --- Verify token before doing anything ---
    bot_info = await _get_me()
    if not bot_info:
        logger.error("Telegram listener aborting — invalid bot token or network error")
        return
    logger.info(f"Telegram bot verified: @{bot_info.get('username')} (id={bot_info.get('id')})")

    # --- Initialise: consume pending updates so we never reply to history ---
    pending = await _get_updates(offset=None, timeout=0)
    if pending:
        offset: int | None = pending[-1]["update_id"] + 1
        logger.info(f"Telegram listener ready — skipped {len(pending)} pending update(s), offset={offset}")
    else:
        offset = None
        logger.info("Telegram listener ready — no pending updates, listening for new messages")

    # --- Main long-poll loop ---
    while True:
        try:
            updates = await _get_updates(offset=offset, timeout=_LONG_POLL_TIMEOUT)

            for update in updates:
                offset = update["update_id"] + 1  # always advance, even for filtered messages

                msg = update.get("message") or update.get("channel_post")
                if not msg:
                    continue

                incoming_chat = msg.get("chat", {})
                incoming_chat_id = incoming_chat.get("id")

                # Log every incoming message chat_id so we can diagnose ID mismatches
                sender = msg.get("from", {})
                sender_name = sender.get("first_name") or sender.get("username") or "unknown"
                logger.debug(
                    f"Telegram update: chat_id={incoming_chat_id} "
                    f"(expected {target_chat_id}), from={sender_name}"
                )

                if incoming_chat_id != target_chat_id:
                    logger.info(
                        f"Telegram: ignoring message from chat_id={incoming_chat_id} "
                        f"(not our target {target_chat_id})"
                    )
                    continue

                # Skip bot messages (including our own)
                if sender.get("is_bot"):
                    continue

                content = msg.get("text", "").strip()
                if not content:
                    logger.debug(f"Telegram: skipping non-text message from {sender_name}")
                    continue

                logger.info(f"Telegram → {sender_name}: {content[:120]}")

                from .graph import AGENT_TIMEZONE, _get_last_ai_content, chat as agent_chat
                from datetime import datetime

                current_time = datetime.now(AGENT_TIMEZONE)
                result = await asyncio.to_thread(
                    agent_chat,
                    agent,
                    "main",
                    content,
                    user_display_name=sender_name,
                    current_time=current_time,
                    channel_type="telegram",
                    is_group_chat=False,
                )

                response = _get_last_ai_content(result["messages"]) or ""
                if response:
                    await _send_message(target_chat_id, response)
                    logger.info(f"Telegram ← Agent: {response[:120]}")

        except asyncio.CancelledError:
            logger.info("Telegram listener cancelled")
            break
        except Exception as e:
            logger.error(f"Telegram poll loop error: {e}", exc_info=True)
            await asyncio.sleep(5)


def start_telegram_listener(agent) -> asyncio.Task | None:
    """Start the Telegram long-poll listener as a background asyncio task.
    Returns None (and logs) if env vars aren't configured."""
    global _task

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id_str:
        logger.info(
            "Telegram listener not started "
            "(TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from .env)"
        )
        return None

    try:
        target_chat_id = int(chat_id_str)
    except ValueError:
        logger.error(f"TELEGRAM_CHAT_ID '{chat_id_str}' is not a valid integer. "
                     f"Find your ID by messaging @userinfobot on Telegram.")
        return None

    if _task and not _task.done():
        logger.warning("Telegram listener already running")
        return _task

    _task = asyncio.create_task(_poll_loop(agent, target_chat_id))
    logger.info(
        f"Telegram listener task created (target chat_id={target_chat_id}, "
        f"long-poll timeout={_LONG_POLL_TIMEOUT}s)"
    )
    return _task


def stop_telegram_listener() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        logger.info("Telegram listener stopped")
    _task = None
