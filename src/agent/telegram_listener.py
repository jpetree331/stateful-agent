"""
Telegram inbound listener — supports two modes:

1. WEBHOOK (recommended when you have a public URL): Telegram pushes updates
   to your server. Zero polling, instant delivery. Set TELEGRAM_WEBHOOK_URL
   (e.g. https://your-subdomain.ngrok-free.app

2. LONG-POLLING (fallback for local-only): Uses getUpdates with timeout=30.
   One request held open; Telegram returns when a message arrives. ~2 req/min when idle.

Both modes: filters to TELEGRAM_CHAT_ID, fetches images/documents, passes to agent.

Required .env:
  TELEGRAM_BOT_TOKEN  — bot token from @BotFather
  TELEGRAM_CHAT_ID    — your chat ID (message @userinfobot to find it)

Optional for webhook mode:
  TELEGRAM_WEBHOOK_URL — public HTTPS URL for Telegram to POST updates (e.g. ngrok)
"""
from __future__ import annotations

import asyncio
import io
import logging
import os

import httpx

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}

logger = logging.getLogger("telegram.listener")

_BASE = "https://api.telegram.org"
_LONG_POLL_TIMEOUT = 30  # seconds Telegram holds the connection waiting for updates

_task: asyncio.Task | None = None
_webhook_chat_id: int | None = None  # Set when using webhook mode, for the route handler


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


async def _fetch_file_bytes(file_id: str) -> bytes | None:
    """Download a Telegram file by file_id. Returns raw bytes or None."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{_BASE}/bot{_token()}/getFile",
                params={"file_id": file_id},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data.get("ok"):
                return None
            file_path = data.get("result", {}).get("file_path")
            if not file_path:
                return None
            dl_resp = await client.get(f"{_BASE}/file/bot{_token()}/{file_path}")
            dl_resp.raise_for_status()
            return dl_resp.content
    except Exception as e:
        logger.warning(f"Telegram → failed to fetch file: {e}")
        return None


async def _fetch_image_as_data_url(file_id: str) -> str | None:
    """Download a Telegram file by file_id, resize for vision, return data URL or None."""
    raw = await _fetch_file_bytes(file_id)
    if not raw:
        return None
    try:
        from PIL import Image
        from .screenshot_tools import _resize_for_vision, _image_to_base64
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img = _resize_for_vision(img)
        b64 = _image_to_base64(img)
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"Telegram → failed to process image: {e}")
        return None


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


async def process_telegram_update(agent, update: dict, target_chat_id: int) -> None:
    """Process a single Telegram update. Used by both webhook and poll modes."""
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return
    incoming_chat_id = msg.get("chat", {}).get("id")
    sender = msg.get("from", {})
    sender_name = sender.get("first_name") or sender.get("username") or "unknown"
    if incoming_chat_id != target_chat_id:
        logger.info(f"Telegram: ignoring chat_id={incoming_chat_id} (expected {target_chat_id})")
        return
    if sender.get("is_bot"):
        return
    content = (msg.get("text") or msg.get("caption") or "").strip()
    image_data_urls: list[str] = []
    photos = msg.get("photo") or []
    if photos:
        file_id = photos[-1].get("file_id")
        if file_id:
            data_url = await _fetch_image_as_data_url(file_id)
            if data_url:
                image_data_urls.append(data_url)
                logger.info("Telegram → fetched photo attachment")
    doc = msg.get("document") or {}
    document_parts: list[str] = []
    if doc:
        mime = (doc.get("mime_type") or "").lower()
        fn = (doc.get("file_name") or "").lower()
        is_image = mime in _IMAGE_TYPES or fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        is_doc = fn.endswith((".pdf", ".txt", ".pptx", ".docx", ".md"))
        file_id = doc.get("file_id")
        if file_id:
            if is_image:
                data_url = await _fetch_image_as_data_url(file_id)
                if data_url:
                    image_data_urls.append(data_url)
                    logger.info(f"Telegram → fetched image document: {doc.get('file_name')}")
            elif is_doc:
                try:
                    data = await _fetch_file_bytes(file_id)
                    if data:
                        from .document_tools import extract_text_from_document_bytes
                        text = extract_text_from_document_bytes(data, doc.get("file_name", ""))
                        if not text.startswith("Error:"):
                            document_parts.append(f"\n\n--- Attachment: {doc.get('file_name')} ---\n{text[:60000]}")
                            logger.info(f"Telegram → extracted document: {doc.get('file_name')}")
                except Exception as e:
                    logger.warning(f"Telegram → failed to fetch/extract document: {e}")
    if document_parts:
        content = (content or "") + "".join(document_parts)
    if not content and not image_data_urls:
        logger.debug(f"Telegram: skipping non-text, non-image from {sender_name}")
        return
    logger.info(f"Telegram → {sender_name}: {(content or '[Image(s) attached]')[:120]}")
    from .graph import AGENT_TIMEZONE, _get_last_ai_content, chat as agent_chat
    from datetime import datetime
    current_time = datetime.now(AGENT_TIMEZONE)
    result = await asyncio.to_thread(
        agent_chat,
        agent,
        "main",
        content or "[Image(s) attached]",
        user_display_name=sender_name,
        current_time=current_time,
        channel_type="telegram",
        is_group_chat=False,
        image_data_urls=image_data_urls if image_data_urls else None,
    )
    response = _get_last_ai_content(result["messages"]) or ""
    if response:
        await _send_message(target_chat_id, response)
        logger.info(f"Telegram ← Agent: {response[:120]}")


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
                offset = update["update_id"] + 1
                await process_telegram_update(agent, update, target_chat_id)

        except asyncio.CancelledError:
            logger.info("Telegram listener cancelled")
            break
        except Exception as e:
            logger.error(f"Telegram poll loop error: {e}", exc_info=True)
            await asyncio.sleep(5)


def get_telegram_webhook_chat_id() -> int | None:
    """Return target chat_id when in webhook mode, else None."""
    return _webhook_chat_id


async def register_telegram_webhook(url: str) -> bool:
    """Register webhook URL with Telegram. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_BASE}/bot{_token()}/setWebhook", params={"url": url})
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info(f"Telegram webhook registered: {url}")
            return True
        logger.error(f"Telegram setWebhook failed: {resp.text[:300]}")
        return False
    except Exception as e:
        logger.error(f"Telegram setWebhook error: {e}")
        return False


async def delete_telegram_webhook() -> None:
    """Remove webhook so getUpdates can be used again."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(f"{_BASE}/bot{_token()}/deleteWebhook")
        logger.info("Telegram webhook removed")
    except Exception as e:
        logger.warning(f"Telegram deleteWebhook error: {e}")


def start_telegram_listener(agent) -> asyncio.Task | None:
    """Start Telegram listener. Uses webhook if TELEGRAM_WEBHOOK_URL is set, else long-poll."""
    global _task

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()

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

    if webhook_url:
        # Webhook mode: store chat_id for the route; caller must register webhook and add route.
        global _webhook_chat_id
        _webhook_chat_id = target_chat_id
        logger.info(f"Telegram webhook mode (chat_id={target_chat_id}) — register via setup_telegram_webhook()")
        return None

    # Long-poll mode
    if _task and not _task.done():
        logger.warning("Telegram listener already running")
        return _task

    _task = asyncio.create_task(_poll_loop(agent, target_chat_id))
    logger.info(
        f"Telegram long-poll task created (target chat_id={target_chat_id}, "
        f"timeout={_LONG_POLL_TIMEOUT}s)"
    )
    return _task


def stop_telegram_listener() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        logger.info("Telegram listener stopped")
    _task = None
