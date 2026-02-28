"""
APScheduler-based cron job scheduler for the agent.

Runs scheduled jobs with full agent context (core memory + hindsight + chat).
"""
from __future__ import annotations

import asyncio
import logging
import os
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .cron_jobs import (
    list_cron_jobs,
    record_run,
    update_cron_job,
    logger as cron_logger,
)
from .graph import build_agent, chat, AGENT_TIMEZONE

logger = logging.getLogger("cron.scheduler")

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


def parse_time(time_str: str) -> tuple[int, int]:
    """
    Parse time string like '7:00 PM' or '19:00' into (hour, minute).
    
    Returns:
        (hour, minute) in 24-hour format
    """
    time_str = time_str.strip().upper()
    
    # Handle AM/PM format
    if "AM" in time_str or "PM" in time_str:
        is_pm = "PM" in time_str
        time_part = time_str.replace("AM", "").replace("PM", "").strip()
        
        if ":" in time_part:
            hour_str, minute_str = time_part.split(":")
            hour = int(hour_str)
            minute = int(minute_str)
        else:
            hour = int(time_part)
            minute = 0
        
        # Convert to 24-hour format
        if is_pm and hour != 12:
            hour += 12
        elif not is_pm and hour == 12:
            hour = 0
    else:
        # 24-hour format
        if ":" in time_str:
            hour_str, minute_str = time_str.split(":")
            hour = int(hour_str)
            minute = int(minute_str)
        else:
            hour = int(time_str)
            minute = 0
    
    return hour, minute


def _get_day_name(day_num: int) -> str:
    """Convert day number (0=Monday) to APScheduler day name."""
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return days[day_num]


def create_trigger_for_job(job: dict) -> CronTrigger | DateTrigger | None:
    """
    Create an APScheduler trigger for a job.
    
    For recurring jobs: CronTrigger with days and time
    For one-time jobs: DateTrigger with specific date/time
    
    Args:
        job: Cron job dict
    
    Returns:
        CronTrigger, DateTrigger, or None if invalid
    """
    try:
        tz_name = job.get("timezone", "America/New_York")
        is_one_time = job.get("is_one_time", False)
        
        if is_one_time:
            # One-time job with specific date
            run_date = job.get("run_date")
            time_str = job.get("schedule_time") or "12:00 PM"
            
            if not run_date:
                return None
            
            hour, minute = parse_time(time_str)
            
            # Parse the date and combine with time
            from datetime import datetime as dt
            run_datetime = dt.strptime(f"{run_date} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
            
            return DateTrigger(
                run_date=run_datetime,
                timezone=ZoneInfo(tz_name),
            )
        else:
            # Recurring job with days of week
            days = job.get("schedule_days", [])
            time_str = job.get("schedule_time", "12:00 PM")
            
            if not days:
                return None
            
            hour, minute = parse_time(time_str)
            day_names = ",".join(_get_day_name(d) for d in days)
            
            return CronTrigger(
                day_of_week=day_names,
                hour=hour,
                minute=minute,
                timezone=ZoneInfo(tz_name),
            )
    except Exception as e:
        logger.error(f"Failed to create trigger for job {job.get('id')}: {e}")
        return None


def _run_cron_job_sync(job: dict) -> None:
    """
    Blocking portion of cron job execution — runs in a thread via asyncio.to_thread().

    AsyncIOScheduler runs execute_cron_job as a coroutine in the event loop. Calling
    blocking I/O (SQLite checkpointer, PostgreSQL, LLM API) directly from a coroutine
    blocks the entire event loop. Running it here in a thread keeps the loop free.
    """
    job_id = job["id"]
    is_one_time = job.get("is_one_time", False)

    # Build the agent (loads core memory, creates SQLite checkpointer)
    agent = build_agent()

    # Route cron output to the main conversation thread so it appears in the dashboard.
    # The agent has full conversation context and the response shows up in chat like an
    # autonomous "wake-up" — the same pattern as Letta/OpenClaw heartbeats.
    instructions = job.get("instructions", "")
    cron_prompt = f"[Cron: {job['name']}]\n\n{instructions}"

    current_time = datetime.now(AGENT_TIMEZONE)

    chat(
        agent,
        thread_id="main",
        user_message=cron_prompt,
        user_display_name="cron",
        current_time=current_time,
        user_id="agent:cron",
        channel_type="internal",
        is_group_chat=False,
    )

    record_run(job_id, "success")
    logger.info(f"Cron job {job_id} completed successfully")

    if is_one_time:
        update_cron_job(job_id, status="paused")
        logger.info(f"One-time job {job_id} completed and deactivated")


async def execute_cron_job(job_id: int):
    """
    Execute a cron job with full agent context.

    Dispatches the blocking work (_run_cron_job_sync) to a thread pool so the
    asyncio event loop stays free during the LLM call and DB operations.
    """
    from .cron_jobs import get_cron_job

    try:
        job = get_cron_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        if job.get("status") != "active":
            logger.info(f"Skipping inactive job {job_id}")
            record_run(job_id, "skipped")
            return

        is_one_time = job.get("is_one_time", False)
        logger.info(f"Executing {'one-time' if is_one_time else 'recurring'} cron job: {job['name']} (id={job_id})")

        # Run blocking I/O in a thread so we don't block the event loop
        await asyncio.to_thread(_run_cron_job_sync, job)

    except Exception as e:
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        logger.error(f"Cron job {job_id} failed: {error_msg}\n{traceback_str}")
        try:
            record_run(job_id, "error", error=f"{error_msg}\n\n{traceback_str}")
        except Exception as rec_err:
            logger.error(f"Failed to record error for job {job_id}: {rec_err}")


def job_listener(event):
    """Listen for job execution events."""
    if event.exception:
        logger.error(f"Job {event.job_id} crashed: {event.exception}")
    else:
        logger.debug(f"Job {event.job_id} executed successfully")


def start_scheduler() -> AsyncIOScheduler:
    """Start the APScheduler and load all active cron jobs."""
    global _scheduler
    
    if _scheduler and _scheduler.running:
        logger.warning("Scheduler already running")
        return _scheduler
    
    _scheduler = AsyncIOScheduler()
    _scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    
    # Load all active jobs
    jobs = list_cron_jobs(status="active")
    for job in jobs:
        add_job_to_scheduler(_scheduler, job)
    
    _scheduler.start()
    logger.info(f"Scheduler started with {len(jobs)} active jobs")
    return _scheduler


def stop_scheduler():
    """Stop the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Scheduler stopped")
        _scheduler = None


def add_job_to_scheduler(scheduler: AsyncIOScheduler, job: dict) -> bool:
    """Add a single job to the scheduler."""
    trigger = create_trigger_for_job(job)
    if not trigger:
        return False
    
    job_id = job["id"]
    
    # Remove existing job if present
    try:
        scheduler.remove_job(f"cron_{job_id}")
    except Exception:
        pass
    
    # Add the job
    scheduler.add_job(
        func=execute_cron_job,
        trigger=trigger,
        id=f"cron_{job_id}",
        args=[job_id],
        replace_existing=True,
        name=job.get("name", f"cron_{job_id}"),
    )
    logger.debug(f"Added job {job_id} to scheduler")
    return True


def remove_job_from_scheduler(job_id: int) -> bool:
    """Remove a job from the scheduler."""
    global _scheduler
    if not _scheduler:
        return False
    
    try:
        _scheduler.remove_job(f"cron_{job_id}")
        logger.debug(f"Removed job {job_id} from scheduler")
        return True
    except Exception:
        return False


def refresh_job_in_scheduler(job_id: int) -> bool:
    """Refresh a job in the scheduler (update or remove if inactive)."""
    from .cron_jobs import get_cron_job
    
    global _scheduler
    if not _scheduler:
        return False
    
    job = get_cron_job(job_id)
    if not job:
        return remove_job_from_scheduler(job_id)
    
    if job.get("status") != "active":
        return remove_job_from_scheduler(job_id)
    
    return add_job_to_scheduler(_scheduler, job)


def reload_all_jobs():
    """Reload all jobs from database into scheduler."""
    global _scheduler
    if not _scheduler:
        return
    
    # Remove all existing cron jobs
    for job in _scheduler.get_jobs():
        if job.id.startswith("cron_"):
            _scheduler.remove_job(job.id)
    
    # Load active jobs
    jobs = list_cron_jobs(status="active")
    for job in jobs:
        add_job_to_scheduler(_scheduler, job)
    
    logger.info(f"Reloaded {len(jobs)} active jobs")


# For running standalone
if __name__ == "__main__":
    import signal
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Start scheduler
    scheduler = start_scheduler()
    
    # Keep running
    def signal_handler(sig, frame):
        print("\nShutting down scheduler...")
        stop_scheduler()
        exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Scheduler running. Press Ctrl+C to stop.")
    
    # Keep the event loop running
    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    finally:
        loop.close()
