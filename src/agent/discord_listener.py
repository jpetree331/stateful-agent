"""
Discord Gateway listener — connects via discord.py WebSocket so the agent appears
online and responds immediately when the user sends a message.

How it works:
  - Uses discord.py's Gateway (persistent WebSocket) instead of REST polling.
  - on_ready: sets bot status to Online and logs the connected username.
  - on_message: fires immediately on any message; filters to the configured
    channel, skips bot messages, shows typing indicator, then calls chat().
  - PNG/JPEG attachments are fetched and passed to the agent for vision.
  - PDF, TXT, PPTX, DOCX, MD attachments are fetched and their text is extracted
    and appended to the message content.
  - Long responses are split at 2000 chars (Discord limit).

Required .env variables:
  DISCORD_BOT_TOKEN   — bot token from Discord Developer Portal
  DISCORD_CHANNEL_ID  — DM channel ID to listen on

Optional:
  DISCORD_POLL_INTERVAL — kept for backwards compat but ignored (Gateway is instant)

Bot permissions needed in Discord Developer Portal → Bot:
  - MESSAGE CONTENT INTENT (required to read message content)
  - Privileged Intents: Server Members + Message Content
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os

logger = logging.getLogger("discord.listener")

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
_DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".pptx", ".docx", ".md"}
_MAX_DOCUMENT_CHARS = 60_000  # per attachment, to avoid context overflow

_client = None
_task: asyncio.Task | None = None


def start_discord_listener(agent) -> asyncio.Task | None:
    """Start the Discord Gateway listener as a background asyncio task.
    Returns None (and logs a message) if env vars aren't configured."""
    global _client, _task

    channel_id_str = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

    if not channel_id_str or not token:
        logger.info(
            "Discord listener not started "
            "(DISCORD_CHANNEL_ID or DISCORD_BOT_TOKEN missing from .env)"
        )
        return None

    try:
        target_channel_id = int(channel_id_str)
    except ValueError:
        logger.error(f"DISCORD_CHANNEL_ID '{channel_id_str}' is not a valid integer")
        return None

    if _task and not _task.done():
        logger.warning("Discord listener already running")
        return _task

    try:
        import discord
    except ImportError:
        logger.error(
            "discord.py is not installed. Run: pip install discord.py>=2.3\n"
            "Discord Gateway listener will not start."
        )
        return None

    intents = discord.Intents.default()
    intents.message_content = True  # Privileged intent — must be enabled in Developer Portal

    _client = discord.Client(intents=intents)

    @_client.event
    async def on_ready():
        logger.info(f"Discord Gateway connected as {_client.user} (id={_client.user.id})")
        await _client.change_presence(status=discord.Status.online)
        logger.info("Discord status set to Online")

    @_client.event
    async def on_message(message: discord.Message):
        # Only process messages in the configured channel
        if message.channel.id != target_channel_id:
            return

        # Skip messages from bots (including ourselves)
        if message.author.bot:
            return

        content = (message.content or "").strip()
        # Allow messages with only image attachments (no text)
        image_data_urls: list[str] = []
        for att in message.attachments:
            ct = (att.content_type or "").lower()
            fn = (att.filename or "").lower()
            if ct in _IMAGE_TYPES or fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                try:
                    import httpx
                    from PIL import Image
                    from .screenshot_tools import _resize_for_vision, _image_to_base64

                    async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            att.url,
                            headers={"Authorization": f"Bot {token}"},
                            timeout=30,
                        )
                        resp.raise_for_status()
                        data = resp.content
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                    img = _resize_for_vision(img)
                    b64 = _image_to_base64(img)
                    image_data_urls.append(f"data:image/jpeg;base64,{b64}")
                    logger.info(f"Discord → fetched image attachment: {att.filename}")
                except Exception as e:
                    logger.warning(f"Discord → failed to fetch image {att.filename}: {e}")

        # Fetch and extract text from document attachments (PDF, TXT, PPTX, DOCX, MD)
        document_parts: list[str] = []
        for att in message.attachments:
            fn = (att.filename or "").lower()
            if not any(fn.endswith(ext) for ext in _DOCUMENT_EXTENSIONS):
                continue
            try:
                import httpx
                from .document_tools import extract_text_from_document_bytes

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        att.url,
                        headers={"Authorization": f"Bot {token}"},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    data = resp.content
                text = extract_text_from_document_bytes(data, att.filename)
                if text.startswith("Error:"):
                    document_parts.append(f"[{att.filename}]: {text}")
                else:
                    if len(text) > _MAX_DOCUMENT_CHARS:
                        text = text[:_MAX_DOCUMENT_CHARS] + f"\n\n[... truncated at {_MAX_DOCUMENT_CHARS:,} chars]"
                    document_parts.append(f"\n\n--- Attachment: {att.filename} ---\n{text}")
                logger.info(f"Discord → extracted document: {att.filename}")
            except Exception as e:
                logger.warning(f"Discord → failed to fetch/extract document {att.filename}: {e}")

        if document_parts:
            content = (content or "") + "".join(document_parts)

        if not content and not image_data_urls:
            return

        username = message.author.display_name or message.author.name or "User"
        display_content = content or "[Image(s) attached]"
        logger.info(f"Discord → {username}: {display_content[:120]}")

        # Show typing indicator while processing
        async with message.channel.typing():
            from .graph import AGENT_TIMEZONE, _get_last_ai_content, chat
            from datetime import datetime

            current_time = datetime.now(AGENT_TIMEZONE)
            result = await asyncio.to_thread(
                chat,
                agent,
                "main",
                content or "[Image(s) attached]",
                user_display_name=username,
                current_time=current_time,
                channel_type="discord",
                is_group_chat=False,
                image_data_urls=image_data_urls if image_data_urls else None,
            )

        response = _get_last_ai_content(result["messages"]) or ""
        if not response:
            return

        # Split at 2000 chars (Discord limit)
        chunks = [response[i : i + 2000] for i in range(0, len(response), 2000)]
        for chunk in chunks:
            try:
                await message.channel.send(chunk)
            except Exception as e:
                logger.error(f"Discord send failed: {e}")

        logger.info(f"Discord ← Agent: {response[:120]}")

    async def _run_client():
        try:
            await _client.start(token)
        except asyncio.CancelledError:
            logger.info("Discord listener task cancelled")
        except Exception as e:
            logger.error(f"Discord Gateway error: {e}", exc_info=True)
        finally:
            if not _client.is_closed():
                await _client.close()

    _task = asyncio.create_task(_run_client())
    logger.info(f"Discord Gateway listener task started (channel {target_channel_id})")
    return _task


async def stop_discord_listener() -> None:
    global _client, _task
    if _client and not _client.is_closed():
        await _client.close()
        logger.info("Discord client closed")
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("Discord listener stopped")
    _client = None
    _task = None
