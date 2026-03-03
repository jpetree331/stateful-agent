"""
FastAPI server for the agent dashboard.

Local dev: Run API + Vite dev server (npm run dev in dashboard/). Open http://localhost:5173.
Public (ngrok): Build dashboard (npm run build), run API, then ngrok http 8000. One URL serves both.
"""
from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

import asyncio
import base64
import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import APIRouter, File, Form, FastAPI, HTTPException, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Configure logging — writes to console AND a rotating file at data/api.log
import logging.handlers

_LOG_DIR = Path(__file__).resolve().parents[2] / "data"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "api.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("agent.api")

from .core_memory import get_all_blocks, update_block, update_system_instructions
from .cron_jobs import (
    COMMON_TIMEZONES,
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    update_cron_job,
    pause_cron_job,
    resume_cron_job,
    clone_cron_job,
    format_days,
    get_timezone_display,
)
from .cron_scheduler import (
    start_scheduler,
    stop_scheduler,
    refresh_job_in_scheduler,
)
from .discord_listener import start_discord_listener, stop_discord_listener
from .telegram_listener import (
    delete_telegram_webhook,
    get_telegram_webhook_chat_id,
    process_telegram_update,
    register_telegram_webhook,
    start_telegram_listener,
    stop_telegram_listener,
)
from .db import check_connection, get_connection, load_messages, setup_schema
from .graph import build_agent, chat, _get_last_ai_content, get_tool_list_for_api
from .notes import (
    list_boards,
    create_board,
    get_board,
    update_board,
    delete_board,
    list_items,
    create_item,
    get_item,
    update_item,
    delete_item,
    list_finished_items,
    add_finished_item,
    archive_finished_item,
)
from .hindsight import recall as hindsight_recall
from .knowledge_bank import (
    delete_file as kb_delete_file,
    get_file_chunks as kb_get_chunks,
    get_file_content as kb_get_content,
    is_configured as kb_is_configured,
    list_files as kb_list_files,
    update_file_tags as kb_update_tags,
    upload_file as kb_upload_file,
    upload_from_url as kb_upload_from_url,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_schema()
    check_connection()
    app.state.agent = build_agent()
    # Start background services
    start_scheduler()
    start_discord_listener(app.state.agent)
    telegram_task = start_telegram_listener(app.state.agent)
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
    if webhook_url:
        await register_telegram_webhook(webhook_url)
    if telegram_task is not None:
        app.state._telegram_poll_task = telegram_task
    yield
    # Cleanup
    stop_scheduler()
    await stop_discord_listener()
    stop_telegram_listener()
    if webhook_url:
        await delete_telegram_webhook()


app = FastAPI(lifespan=lifespan)
api_router = APIRouter()

# Optional: password-protect dashboard (for ngrok). Set DASHBOARD_PASSWORD in .env.
# When set, browser shows a login popup. Username can be anything; password must match.
_DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "").strip()


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth when DASHBOARD_PASSWORD is set."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not _DASHBOARD_PASSWORD:
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                if password == _DASHBOARD_PASSWORD:
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Dashboard", charset="UTF-8"'},
            content="Authentication required",
        )


app.add_middleware(DashboardAuthMiddleware)

# CORS_ORIGINS env var: comma-separated list of extra allowed origins (e.g. your ngrok URL).
# Example: CORS_ORIGINS=https://your-dashboard.netlify.app
_extra_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"] + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "main"
    user_id: str | None = None
    channel_type: str | None = None  # "discord", "telegram", or "local"
    is_group_chat: bool = False
    image_data_urls: list[str] | None = None
    document_text: str | None = None  # Extracted text from PDF/DOCX/PPTX/TXT/MD


class ChatResponse(BaseModel):
    response: str


class CoreMemoryBlock(BaseModel):
    content: str
    read_only: bool = False


class CoreMemoryUpdateRequest(BaseModel):
    content: str


class CoreMemoryResponse(BaseModel):
    blocks: dict[str, CoreMemoryBlock]


def _run_chat(
    message: str,
    thread_id: str = "main",
    user_id: str | None = None,
    channel_type: str | None = None,
    is_group_chat: bool = False,
    image_data_urls: list[str] | None = None,
    document_text: str | None = None,
):
    """Run chat with optional images and document text."""
    full_message = (message or "").strip()
    if document_text:
        full_message = (full_message + "\n\n" + document_text).strip()
    if not full_message:
        full_message = "[Image(s) attached]"
    return chat(
        app.state.agent,
        thread_id,
        full_message,
        user_display_name=os.environ.get("USER_DISPLAY_NAME", "User"),
        user_id=user_id,
        channel_type=channel_type,
        is_group_chat=is_group_chat,
        image_data_urls=image_data_urls,
    )


@api_router.post("/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest):
    """Handle a chat message and return the assistant response."""
    preview = req.message[:120].replace("\n", " ")
    logger.info("POST /chat thread=%s channel=%s msg=%r", req.thread_id, req.channel_type, preview)
    try:
        result = _run_chat(
            req.message,
            thread_id=req.thread_id,
            user_id=req.user_id,
            channel_type=req.channel_type,
            is_group_chat=req.is_group_chat,
            image_data_urls=req.image_data_urls,
            document_text=req.document_text,
        )
    except RuntimeError as e:
        logger.error("POST /chat RuntimeError: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("POST /chat unhandled exception:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")
    last = _get_last_ai_content(result["messages"])
    logger.info("POST /chat → response length=%d chars", len(last or ""))
    return ChatResponse(response=last or "")


@api_router.post("/chat/upload", response_model=ChatResponse)
async def post_chat_with_files(
    message: str = Form(""),
    thread_id: str = Form("main"),
    files: list[UploadFile] = File(default=[]),
):
    """Handle chat with file attachments (images + documents). Same formats as Discord."""
    image_data_urls: list[str] = []
    document_parts: list[str] = []
    _IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    _DOC_EXT = {".pdf", ".txt", ".pptx", ".docx", ".md"}
    _MAX_DOC_CHARS = 60_000

    for f in files or []:
        fn = (f.filename or "").lower()
        ext = "." + fn.split(".")[-1] if "." in fn else ""
        try:
            data = await f.read()
        except Exception as e:
            logger.warning("chat/upload: failed to read %s: %s", fn, e)
            continue
        if ext in _IMAGE_EXT:
            try:
                from PIL import Image
                from .screenshot_tools import _resize_for_vision, _image_to_base64
                import io
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img = _resize_for_vision(img)
                b64 = _image_to_base64(img)
                image_data_urls.append(f"data:image/jpeg;base64,{b64}")
            except Exception as e:
                logger.warning("chat/upload: failed to process image %s: %s", fn, e)
        elif ext in _DOC_EXT:
            try:
                from .document_tools import extract_text_from_document_bytes
                text = extract_text_from_document_bytes(data, f.filename or "")
                if not text.startswith("Error:"):
                    if len(text) > _MAX_DOC_CHARS:
                        text = text[:_MAX_DOC_CHARS] + f"\n\n[... truncated at {_MAX_DOC_CHARS:,} chars]"
                    document_parts.append(f"\n\n--- Attachment: {f.filename} ---\n{text}")
            except Exception as e:
                logger.warning("chat/upload: failed to extract document %s: %s", fn, e)

    doc_text = "".join(document_parts) if document_parts else None
    full_msg = (message or "").strip()
    if not full_msg and not image_data_urls and not doc_text:
        raise HTTPException(status_code=400, detail="Message or files required")
    try:
        result = _run_chat(
            full_msg or "[Image(s) attached]",
            thread_id=thread_id,
            image_data_urls=image_data_urls if image_data_urls else None,
            document_text=doc_text,
        )
    except RuntimeError as e:
        logger.error("POST /chat/upload RuntimeError: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("POST /chat/upload: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")
    last = _get_last_ai_content(result["messages"])
    return ChatResponse(response=last or "")


@api_router.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """
    Telegram webhook endpoint. Telegram POSTs updates here when TELEGRAM_WEBHOOK_URL is set.
    Returns 200 immediately; processes update in background.
    """
    chat_id = get_telegram_webhook_chat_id()
    if chat_id is None:
        raise HTTPException(status_code=503, detail="Telegram webhook not configured")
    try:
        update = await request.json()
    except Exception as e:
        logger.warning("telegram-webhook: invalid JSON: %s", e)
        return {"ok": True}
    agent = request.app.state.agent
    asyncio.create_task(process_telegram_update(agent, update, chat_id))
    return {"ok": True}


@api_router.get("/tools")
def get_tools():
    """Get all tools the agent has access to, grouped by category."""
    return {"categories": get_tool_list_for_api()}


@api_router.get("/core-memory", response_model=CoreMemoryResponse)
def get_core_memory():
    """Get all core memory blocks."""
    blocks = get_all_blocks()
    return CoreMemoryResponse(
        blocks={
            "system_instructions": CoreMemoryBlock(
                content=blocks.get("system_instructions", ""),
                read_only=True,
            ),
            "user": CoreMemoryBlock(
                content=blocks.get("user", ""),
                read_only=False,
            ),
            "identity": CoreMemoryBlock(
                content=blocks.get("identity", ""),
                read_only=False,
            ),
            "ideaspace": CoreMemoryBlock(
                content=blocks.get("ideaspace", ""),
                read_only=False,
            ),
        }
    )


@api_router.post("/core-memory/{block_type}")
def update_core_memory(block_type: str, req: CoreMemoryUpdateRequest):
    """Update a core memory block. Users can edit all blocks; read_only flag protects from AI edits."""
    if block_type == "system_instructions":
        update_system_instructions(req.content)
        return {"success": True, "message": "Updated system_instructions"}
    
    if block_type not in ("user", "identity", "ideaspace"):
        raise HTTPException(
            status_code=400,
            detail=f"Block type '{block_type}' is invalid"
        )
    
    success, message = update_block(block_type, req.content)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message}


# === Cron Job Endpoints ===

class CronJobCreate(BaseModel):
    name: str
    instructions: str
    schedule_days: list[int] | None = None  # 0=Monday, 6=Sunday (for recurring)
    schedule_time: str | None = None  # e.g., "7:00 PM"
    timezone: str = "America/New_York"
    description: str | None = None
    run_date: str | None = None  # YYYY-MM-DD format for one-time jobs


class CronJobUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None
    schedule_days: list[int] | None = None
    schedule_time: str | None = None
    timezone: str | None = None
    description: str | None = None
    run_date: str | None = None
    status: str | None = None  # "active" or "paused"


class CronJobResponse(BaseModel):
    id: int
    name: str
    description: str | None
    instructions: str
    timezone: str
    timezone_display: str
    schedule_days: list[int] | None
    schedule_days_display: str
    schedule_time: str | None
    run_date: str | None
    is_one_time: bool
    status: str
    created_by: str
    created_at: str
    updated_at: str
    last_run_at: str | None
    last_run_status: str | None
    last_run_error: str | None
    run_count: int


class CronJobListResponse(BaseModel):
    jobs: list[CronJobResponse]


class TimezoneOption(BaseModel):
    value: str
    label: str


class TimezonesResponse(BaseModel):
    timezones: list[TimezoneOption]


def _job_to_response(job: dict) -> CronJobResponse:
    """Convert job dict to response model."""
    is_one_time = job.get("is_one_time", False)
    
    # Format schedule display
    # run_date comes from PostgreSQL as datetime.date — convert to ISO string for display/response
    run_date_str = job["run_date"].isoformat() if job.get("run_date") else None
    if is_one_time:
        schedule_display = f"One-time on {run_date_str or 'unknown date'}"
    else:
        schedule_display = format_days(job.get("schedule_days") or [])

    return CronJobResponse(
        id=job["id"],
        name=job["name"],
        description=job.get("description"),
        instructions=job["instructions"],
        timezone=job["timezone"],
        timezone_display=get_timezone_display(job["timezone"]),
        schedule_days=job.get("schedule_days"),
        schedule_days_display=schedule_display,
        schedule_time=job.get("schedule_time"),
        run_date=run_date_str,
        is_one_time=is_one_time,
        status=job["status"],
        created_by=job["created_by"],
        created_at=job["created_at"].isoformat() if job.get("created_at") else None,
        updated_at=job["updated_at"].isoformat() if job.get("updated_at") else None,
        last_run_at=job["last_run_at"].isoformat() if job.get("last_run_at") else None,
        last_run_status=job.get("last_run_status"),
        last_run_error=job.get("last_run_error"),
        run_count=job.get("run_count", 0),
    )


@api_router.get("/cron/timezones", response_model=TimezonesResponse)
def get_timezones():
    """Get list of available timezones."""
    return TimezonesResponse(
        timezones=[TimezoneOption(value=v, label=l) for v, l in COMMON_TIMEZONES]
    )


@api_router.get("/cron/jobs", response_model=CronJobListResponse)
def get_cron_jobs(status: str | None = None):
    """Get all cron jobs, ordered by newest first."""
    jobs = list_cron_jobs(status=status)
    return CronJobListResponse(jobs=[_job_to_response(j) for j in jobs])


@api_router.post("/cron/jobs", response_model=CronJobResponse)
def create_job(req: CronJobCreate):
    """Create a new cron job (recurring or one-time)."""
    # Validate one-time vs recurring
    if req.run_date:
        # One-time job
        if not req.schedule_time:
            raise HTTPException(status_code=400, detail="Time is required for one-time jobs")
    else:
        # Recurring job
        if not req.schedule_days:
            raise HTTPException(status_code=400, detail="Days are required for recurring jobs")
        if not req.schedule_time:
            raise HTTPException(status_code=400, detail="Time is required for recurring jobs")
    
    job = create_cron_job(
        name=req.name,
        instructions=req.instructions,
        schedule_days=req.schedule_days,
        schedule_time=req.schedule_time,
        timezone=req.timezone,
        description=req.description,
        created_by="user",
        run_date=req.run_date,
    )
    if not job:
        raise HTTPException(status_code=500, detail="Failed to create cron job")
    
    # Add to scheduler
    refresh_job_in_scheduler(job["id"])
    
    return _job_to_response(job)


@api_router.get("/cron/jobs/{job_id}", response_model=CronJobResponse)
def get_job(job_id: int):
    """Get a single cron job."""
    job = get_cron_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return _job_to_response(job)


@api_router.put("/cron/jobs/{job_id}", response_model=CronJobResponse)
def update_job(job_id: int, req: CronJobUpdate):
    """Update a cron job."""
    # Check if job exists
    existing = get_cron_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    # Build update dict
    updates = {}
    for field in ["name", "instructions", "schedule_days", "schedule_time", "timezone", "description", "run_date", "status"]:
        value = getattr(req, field)
        if value is not None:
            updates[field] = value
    
    if not updates:
        return _job_to_response(existing)
    
    job = update_cron_job(job_id, **updates)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to update cron job")
    
    # Refresh in scheduler
    refresh_job_in_scheduler(job_id)
    
    return _job_to_response(job)


@api_router.delete("/cron/jobs/{job_id}")
def delete_job(job_id: int):
    """Delete a cron job."""
    # Check if job exists
    existing = get_cron_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    # Remove from scheduler first
    refresh_job_in_scheduler(job_id)  # This will remove it since it's being deleted
    
    # Delete from database
    if not delete_cron_job(job_id):
        raise HTTPException(status_code=500, detail="Failed to delete cron job")
    
    return {"success": True, "message": f"Cron job {job_id} deleted"}


@api_router.post("/cron/jobs/{job_id}/pause", response_model=CronJobResponse)
def pause_job(job_id: int):
    """Pause a cron job."""
    job = pause_cron_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    # Refresh in scheduler (will remove it)
    refresh_job_in_scheduler(job_id)
    
    return _job_to_response(job)


@api_router.post("/cron/jobs/{job_id}/resume", response_model=CronJobResponse)
def resume_job(job_id: int):
    """Resume a paused cron job."""
    job = resume_cron_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    # Refresh in scheduler (will add it back)
    refresh_job_in_scheduler(job_id)
    
    return _job_to_response(job)


@api_router.post("/cron/jobs/{job_id}/clone", response_model=CronJobResponse)
def clone_job(job_id: int):
    """Clone an existing cron job."""
    # Check if original exists
    existing = get_cron_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    new_name = f"{existing['name']} (Copy)"
    job = clone_cron_job(job_id, new_name=new_name)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to clone cron job")
    
    # Add to scheduler if active
    refresh_job_in_scheduler(job["id"])
    
    return _job_to_response(job)


class MessageItem(BaseModel):
    role: str
    content: str
    metadata: dict = {}


class MessagesResponse(BaseModel):
    messages: list[MessageItem]


@api_router.get("/messages", response_model=MessagesResponse)
def get_messages(thread_id: str = "main", limit: int = 200):
    """Get conversation history for a thread (for dashboard display)."""
    rows = load_messages(thread_id, limit=limit, include_metadata=True)
    return MessagesResponse(
        messages=[
            MessageItem(
                role=r["role"],
                content=r["content"],
                metadata=r.get("metadata") or {},
            )
            for r in rows
        ]
    )


class HeartbeatSession(BaseModel):
    timestamp: str
    prompt: str
    response: str | None
    response_at: str | None


class HeartbeatStatusResponse(BaseModel):
    last_run: str | None
    interval_minutes: int
    next_expected: str | None
    total_runs: int


@api_router.get("/heartbeat/status", response_model=HeartbeatStatusResponse)
def get_heartbeat_status():
    """Last heartbeat time, interval, and total run count."""
    interval = int(os.environ.get("HEARTBEAT_INTERVAL_MINUTES", "60"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at,
                       (SELECT COUNT(*) FROM messages
                        WHERE thread_id = 'main' AND role = 'user'
                          AND metadata->>'role_display' = 'heartbeat') AS total
                FROM messages
                WHERE thread_id = 'main' AND role = 'user'
                  AND metadata->>'role_display' = 'heartbeat'
                ORDER BY created_at DESC LIMIT 1
                """
            )
            row = cur.fetchone()
    if not row:
        return HeartbeatStatusResponse(
            last_run=None, interval_minutes=interval,
            next_expected=None, total_runs=0,
        )
    from datetime import timedelta
    last_run_dt = row["created_at"]
    next_dt = last_run_dt + timedelta(minutes=interval)
    return HeartbeatStatusResponse(
        last_run=last_run_dt.isoformat(),
        interval_minutes=interval,
        next_expected=next_dt.isoformat(),
        total_runs=int(row["total"]),
    )


@api_router.get("/heartbeat/sessions")
def get_heartbeat_sessions(limit: int = 50):
    """Heartbeat session ledger — each prompt paired with the agent's response."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT h.content    AS prompt,
                       h.created_at AS timestamp,
                       a.content    AS response,
                       a.created_at AS response_at
                FROM messages h
                LEFT JOIN LATERAL (
                    SELECT content, created_at FROM messages
                    WHERE thread_id = h.thread_id
                      AND idx = h.idx + 1
                      AND role = 'assistant'
                ) a ON true
                WHERE h.thread_id = 'main' AND h.role = 'user'
                  AND h.metadata->>'role_display' = 'heartbeat'
                ORDER BY h.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return {
        "sessions": [
            HeartbeatSession(
                timestamp=r["timestamp"].isoformat(),
                prompt=r["prompt"],
                response=r["response"],
                response_at=r["response_at"].isoformat() if r["response_at"] else None,
            )
            for r in rows
        ]
    }


@api_router.get("/health")
def health():
    return {"status": "ok"}


# === Notes (boards + items) ===

class NotesBoardCreate(BaseModel):
    name: str


class NotesBoardUpdate(BaseModel):
    name: str


class NotesItemCreate(BaseModel):
    item_type: str  # "note" or "checklist"
    content: dict | None = None
    position: dict | None = None
    size: dict | None = None
    background_color: str = "#fef08a"
    header_color: str = "#eab308"


class NotesItemUpdate(BaseModel):
    item_type: str | None = None
    content: dict | None = None
    position: dict | None = None
    size: dict | None = None
    background_color: str | None = None
    header_color: str | None = None


@api_router.get("/notes/boards")
def get_notes_boards():
    """List all notes boards."""
    return {"boards": list_boards()}


@api_router.post("/notes/boards")
def post_notes_board(req: NotesBoardCreate):
    """Create a new notes board."""
    board = create_board(req.name.strip() or "Untitled")
    if not board:
        raise HTTPException(status_code=500, detail="Failed to create board")
    return board


@api_router.get("/notes/boards/{board_id}")
def get_notes_board(board_id: int):
    """Get a single board."""
    board = get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@api_router.put("/notes/boards/{board_id}")
def put_notes_board(board_id: int, req: NotesBoardUpdate):
    """Rename a board."""
    board = update_board(board_id, req.name.strip() or "Untitled")
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@api_router.delete("/notes/boards/{board_id}")
def delete_notes_board(board_id: int):
    """Delete a board and all its items. User-only."""
    if not delete_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    return {"success": True}


@api_router.get("/notes/boards/{board_id}/items")
def get_notes_items(board_id: int):
    """List all items on a board."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    return {"items": list_items(board_id)}


@api_router.post("/notes/boards/{board_id}/items")
def post_notes_item(board_id: int, req: NotesItemCreate):
    """Create a new note or checklist item."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    if req.item_type not in ("note", "checklist"):
        raise HTTPException(status_code=400, detail="item_type must be 'note' or 'checklist'")
    item = create_item(
        board_id,
        req.item_type,
        content=req.content,
        position=req.position,
        size=req.size,
        background_color=req.background_color,
        header_color=req.header_color,
    )
    if not item:
        raise HTTPException(status_code=500, detail="Failed to create item")
    return item


@api_router.get("/notes/items/{item_id}")
def get_notes_item(item_id: int):
    """Get a single item."""
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@api_router.put("/notes/items/{item_id}")
def put_notes_item(item_id: int, req: NotesItemUpdate):
    """Update an item. AI can use this."""
    item = update_item(
        item_id,
        item_type=req.item_type,
        content=req.content,
        position=req.position,
        size=req.size,
        background_color=req.background_color,
        header_color=req.header_color,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@api_router.delete("/notes/items/{item_id}")
def delete_notes_item(item_id: int):
    """Delete an item. User-only."""
    if not delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True}


class FinishedItemCreate(BaseModel):
    text: str
    source_checklist_id: int | None = None


@api_router.get("/notes/boards/{board_id}/finished")
def get_notes_finished(board_id: int):
    """List finished items for a board."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    return {"items": list_finished_items(board_id)}


@api_router.post("/notes/boards/{board_id}/finished")
def post_notes_finished(board_id: int, req: FinishedItemCreate):
    """Add a finished item (moved from checklist)."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    item = add_finished_item(board_id, req.text.strip(), source_checklist_id=req.source_checklist_id)
    if not item:
        raise HTTPException(status_code=500, detail="Failed to add finished item")
    return item


@api_router.post("/notes/boards/{board_id}/finished/{finished_id}/archive")
def archive_notes_finished(board_id: int, finished_id: int):
    """Archive a finished item (moves to hidden archive, AI can read)."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    if not archive_finished_item(board_id, finished_id):
        raise HTTPException(status_code=404, detail="Finished item not found")
    return {"success": True}


def _format_board_for_ai(board_id: int) -> str:
    """Format board items as plain text for AI prompts."""
    import re

    board = get_board(board_id)
    if not board:
        return ""
    items = list_items(board_id)
    lines = [f"Board: {board.get('name', 'Untitled')}", ""]
    for i, item in enumerate(items, 1):
        itype = item.get("item_type", "note")
        content = item.get("content") or {}
        title = (content.get("title") or "").strip()
        if itype == "note":
            html = content.get("html") or ""
            md = content.get("markdown") or ""
            body = md or (re.sub(r"<[^>]+>", " ", html).strip() if html else "")
            lines.append(f"[Note {i}]" + (f" {title}" if title else ""))
            if body:
                lines.append(body)
        elif itype == "checklist":
            lines.append(f"[Checklist {i}]" + (f" {title}" if title else ""))
            for it in content.get("items") or []:
                txt = (it.get("text") or "").strip()
                if txt:
                    lines.append(f"  - {'[x]' if it.get('checked') else '[ ]'} {txt}")
        elif itype == "doc":
            lines.append(f"[Doc {i}] {title or 'Untitled'}")
            html = content.get("html") or ""
            if html:
                lines.append(re.sub(r"<[^>]+>", " ", html).strip()[:500])
        lines.append("")
    return "\n".join(lines).strip()


class HindsightRecallRequest(BaseModel):
    query: str


@api_router.post("/notes/boards/{board_id}/summarize")
def notes_summarize_board(board_id: int):
    """Summarize board content via the agent."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    text = _format_board_for_ai(board_id)
    if not text.strip():
        return {"summary": "This board is empty."}
    prompt = f"Summarize the following notes board content in 2–4 concise paragraphs. Focus on key themes, tasks, and ideas:\n\n{text}"
    try:
        result = chat(
            app.state.agent,
            "__notes_ai__",
            prompt,
            user_display_name=os.environ.get("USER_DISPLAY_NAME", "User"),
            channel_type="notes",
        )
        summary = _get_last_ai_content(result["messages"]) or "Could not generate summary."
        return {"summary": summary}
    except Exception as e:
        logger.exception("notes summarize failed")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/notes/boards/{board_id}/organize")
def notes_organize_board(board_id: int):
    """Suggest grouping or layout for board content via the agent."""
    if not get_board(board_id):
        raise HTTPException(status_code=404, detail="Board not found")
    text = _format_board_for_ai(board_id)
    if not text.strip():
        return {"suggestions": "This board is empty. Add some notes first."}
    prompt = f"Based on these notes, suggest how to group or organize them. Propose 2–4 logical groups with short names and which items belong in each. Be concise:\n\n{text}"
    try:
        result = chat(
            app.state.agent,
            "__notes_ai__",
            prompt,
            user_display_name=os.environ.get("USER_DISPLAY_NAME", "User"),
            channel_type="notes",
        )
        suggestions = _get_last_ai_content(result["messages"]) or "Could not generate suggestions."
        return {"suggestions": suggestions}
    except Exception as e:
        logger.exception("notes organize failed")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/notes/hindsight-recall")
def notes_hindsight_recall(req: HindsightRecallRequest):
    """Run Hindsight recall and return results for the Notes sidebar."""
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    try:
        result = hindsight_recall(None, query)
        return {"results": result}
    except Exception as e:
        logger.exception("hindsight recall failed")
        raise HTTPException(status_code=500, detail=str(e))


# === Knowledge Bank (data tab) ===

@api_router.get("/knowledge/status")
def knowledge_status():
    """Check if Knowledge Bank is configured and optionally test embedding."""
    import os
    configured = kb_is_configured()
    base_url = os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    # Mask URL for privacy but show enough to verify (e.g. chutes-qwen-qwen3-embedding-8b)
    url_hint = base_url.split("//")[-1].split("/")[0][:50] if base_url else ""
    return {
        "configured": configured,
        "embedding_base": url_hint or None,
    }


@api_router.get("/knowledge/files")
def knowledge_list_files(search: str | None = None):
    """List knowledge files. Optional ?search= for filename/tag filter."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    return {"files": kb_list_files(search_query=search)}


@api_router.post("/knowledge/upload")
async def knowledge_upload(
    file: UploadFile = File(...),
    tags: str = Form(""),
):
    """Upload a document (PDF, TXT, DOCX, PPTX, MD). Supports multiple files via repeated file param."""
    logger.info("POST /knowledge/upload received: filename=%s size=%s", file.filename, file.size)
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    data = await file.read()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    result = kb_upload_file(data, file.filename or "unknown", tags=tag_list)
    if not result.get("success"):
        logger.warning("Knowledge upload failed: %s", result.get("error"))
        raise HTTPException(status_code=400, detail=result.get("error", "Upload failed"))
    logger.info("Knowledge upload success: file_id=%s", result.get("file", {}).get("id"))
    return result


@api_router.post("/knowledge/upload-bulk")
async def knowledge_upload_bulk(
    files: list[UploadFile] = File(...),
    tags: str = Form(""),
):
    """Upload multiple documents at once."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    if not files:
        raise HTTPException(status_code=400, detail="At least one file required")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = []
    for f in files:
        data = await f.read()
        result = kb_upload_file(data, f.filename or "unknown", tags=tag_list)
        results.append({"filename": f.filename, **result})
    return {"results": results}


@api_router.post("/knowledge/upload-url")
async def knowledge_upload_url(url: str = Form(...), filename: str | None = Form(None)):
    """Upload content from a URL (HTML or plain text)."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    if not (url and url.strip()):
        raise HTTPException(status_code=400, detail="URL is required")
    result = kb_upload_from_url(url.strip(), filename=filename or None)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Upload failed"))
    return result


class KnowledgeTagsUpdate(BaseModel):
    tags: list[str] = []


@api_router.patch("/knowledge/files/{file_id}/tags")
def knowledge_update_tags(file_id: int, req: KnowledgeTagsUpdate):
    """Update tags for a file."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    if not kb_update_tags(file_id, req.tags):
        raise HTTPException(status_code=404, detail="File not found")
    return {"success": True}


@api_router.get("/knowledge/files/{file_id}")
def knowledge_get_file(file_id: int):
    """Get full file content (reconstructed from chunks)."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    content = kb_get_content(file_id)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": content}


@api_router.get("/knowledge/files/{file_id}/chunks")
def knowledge_get_chunks(file_id: int):
    """Get chunks for a file (expand view)."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    chunks = kb_get_chunks(file_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="File not found")
    return {"chunks": chunks}


@api_router.delete("/knowledge/files/{file_id}")
def knowledge_delete_file(file_id: int):
    """Delete a knowledge file and its chunks."""
    if not kb_is_configured():
        raise HTTPException(status_code=503, detail="Knowledge Bank not configured (KNOWLEDGE_DATABASE_URL)")
    if not kb_delete_file(file_id):
        raise HTTPException(status_code=404, detail="File not found")
    return {"success": True}


class AnalyzeScreenshotRequest(BaseModel):
    image_data_url: str  # full data URL: "data:image/png;base64,..."
    prompt: str = "Describe in detail what you see on the screen. Note any text, UI elements, open applications, and anything important."


class AnalyzeScreenshotResponse(BaseModel):
    description: str


@api_router.post("/analyze-screenshot", response_model=AnalyzeScreenshotResponse)
def analyze_screenshot_endpoint(req: AnalyzeScreenshotRequest):
    """
    Accept a base64-encoded screenshot from the overlay, run it through the
    vision model (resized), and return a plain-text description.

    The overlay sends that description as a normal chat message, keeping image
    bytes out of the main agent context window entirely.
    """
    import base64
    import io

    vision_model = (
        os.environ.get("VISION_MODEL_NAME")
        or os.environ.get("OPENAI_MODEL_NAME")
        or "gpt-4o-mini"
    )
    vision_base_url = os.environ.get("VISION_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "(default OpenAI)"
    logger.info(
        "POST /analyze-screenshot prompt=%r  model=%s  base_url=%s",
        req.prompt[:80],
        vision_model,
        vision_base_url,
    )

    try:
        from PIL import Image
    except ImportError:
        logger.error("/analyze-screenshot: Pillow not installed")
        raise HTTPException(status_code=500, detail="Pillow not installed on server. Run: pip install Pillow")

    # Strip the data URL prefix to get raw base64
    try:
        _header, b64_data = req.image_data_url.split(",", 1)
    except ValueError:
        logger.error("/analyze-screenshot: malformed image_data_url (no comma separator)")
        raise HTTPException(status_code=400, detail="image_data_url must be a valid data URL (data:image/...;base64,...)")

    try:
        img_bytes = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(img_bytes))
        logger.info("/analyze-screenshot: decoded image size=%s mode=%s", img.size, img.mode)
    except Exception as e:
        logger.error("/analyze-screenshot: image decode failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {e}")

    # Reuse the same resize + vision logic from screenshot_tools
    from .screenshot_tools import _resize_for_vision, _image_to_base64, _call_vision

    img = _resize_for_vision(img)
    logger.info("/analyze-screenshot: resized to %s, encoding to base64", img.size)
    b64 = _image_to_base64(img)
    logger.info("/analyze-screenshot: base64 length=%d chars, calling vision model", len(b64))

    try:
        description = _call_vision(b64, req.prompt)
        logger.info("/analyze-screenshot: vision succeeded, response length=%d chars", len(description))
    except Exception as e:
        full_tb = traceback.format_exc()
        logger.error(
            "/analyze-screenshot: vision call FAILED\n"
            "  model=%s\n  base_url=%s\n  error=%s\n%s",
            vision_model,
            vision_base_url,
            e,
            full_tb,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Vision analysis failed: {e}\n"
                f"Model: {vision_model} | Base URL: {vision_base_url}\n"
                f"Check data/api.log for the full traceback.\n"
                f"Tip: set VISION_BASE_URL in .env if your vision model uses a different endpoint than your main model."
            ),
        )

    return AnalyzeScreenshotResponse(description=description)


# Mount API under /api (dashboard expects /api/chat, /api/messages, etc.)
app.include_router(api_router, prefix="/api")

# Serve built dashboard from same origin (for ngrok: one tunnel to 8000 serves everything)
_DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
if _DASHBOARD_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DASHBOARD_DIST), html=True), name="dashboard")
else:
    logger.warning(
        "Dashboard dist not found at %s — run 'cd dashboard && npm run build' to enable. "
        "Use Vite dev server (npm run dev) for local development.",
        _DASHBOARD_DIST,
    )


if __name__ == "__main__":
    import uvicorn

    # Railway (and most cloud platforms) inject a PORT env var.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "src.agent.api:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
