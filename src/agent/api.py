"""
Minimal FastAPI server for local dashboard testing.

Run: python -m src.agent.api
Then open http://localhost:5173 (Vite dev server) or point the dashboard at http://localhost:8000.
"""
from __future__ import annotations

import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging — writes to console AND a rotating file at data/api.log
import logging.handlers
from pathlib import Path

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
logger = logging.getLogger("rowan.api")

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
from .telegram_listener import start_telegram_listener, stop_telegram_listener
from .db import check_connection, load_messages, setup_schema
from .graph import build_agent, chat, _get_last_ai_content


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_schema()
    check_connection()
    app.state.agent = build_agent()
    # Start background services
    start_scheduler()
    start_discord_listener(app.state.agent)
    start_telegram_listener(app.state.agent)
    yield
    # Cleanup
    stop_scheduler()
    await stop_discord_listener()
    stop_telegram_listener()


app = FastAPI(lifespan=lifespan)

# CORS_ORIGINS env var: comma-separated list of extra allowed origins (e.g. your Netlify URL).
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


class ChatResponse(BaseModel):
    response: str


class CoreMemoryBlock(BaseModel):
    content: str
    read_only: bool = False


class CoreMemoryUpdateRequest(BaseModel):
    content: str


class CoreMemoryResponse(BaseModel):
    blocks: dict[str, CoreMemoryBlock]


@app.post("/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest):
    """Handle a chat message and return the assistant response."""
    preview = req.message[:120].replace("\n", " ")
    logger.info("POST /chat thread=%s channel=%s msg=%r", req.thread_id, req.channel_type, preview)
    try:
        result = chat(
            app.state.agent,
            req.thread_id,
            req.message,
            user_display_name=os.environ.get("USER_DISPLAY_NAME", "User"),
            user_id=req.user_id,
            channel_type=req.channel_type,
            is_group_chat=req.is_group_chat,
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


@app.get("/core-memory", response_model=CoreMemoryResponse)
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


@app.post("/core-memory/{block_type}")
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


@app.get("/cron/timezones", response_model=TimezonesResponse)
def get_timezones():
    """Get list of available timezones."""
    return TimezonesResponse(
        timezones=[TimezoneOption(value=v, label=l) for v, l in COMMON_TIMEZONES]
    )


@app.get("/cron/jobs", response_model=CronJobListResponse)
def get_cron_jobs(status: str | None = None):
    """Get all cron jobs, ordered by newest first."""
    jobs = list_cron_jobs(status=status)
    return CronJobListResponse(jobs=[_job_to_response(j) for j in jobs])


@app.post("/cron/jobs", response_model=CronJobResponse)
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


@app.get("/cron/jobs/{job_id}", response_model=CronJobResponse)
def get_job(job_id: int):
    """Get a single cron job."""
    job = get_cron_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return _job_to_response(job)


@app.put("/cron/jobs/{job_id}", response_model=CronJobResponse)
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


@app.delete("/cron/jobs/{job_id}")
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


@app.post("/cron/jobs/{job_id}/pause", response_model=CronJobResponse)
def pause_job(job_id: int):
    """Pause a cron job."""
    job = pause_cron_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    # Refresh in scheduler (will remove it)
    refresh_job_in_scheduler(job_id)
    
    return _job_to_response(job)


@app.post("/cron/jobs/{job_id}/resume", response_model=CronJobResponse)
def resume_job(job_id: int):
    """Resume a paused cron job."""
    job = resume_cron_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    
    # Refresh in scheduler (will add it back)
    refresh_job_in_scheduler(job_id)
    
    return _job_to_response(job)


@app.post("/cron/jobs/{job_id}/clone", response_model=CronJobResponse)
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


@app.get("/messages", response_model=MessagesResponse)
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


@app.get("/health")
def health():
    return {"status": "ok"}


class AnalyzeScreenshotRequest(BaseModel):
    image_data_url: str  # full data URL: "data:image/png;base64,..."
    prompt: str = "Describe in detail what you see on the screen. Note any text, UI elements, open applications, and anything important."


class AnalyzeScreenshotResponse(BaseModel):
    description: str


@app.post("/analyze-screenshot", response_model=AnalyzeScreenshotResponse)
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
