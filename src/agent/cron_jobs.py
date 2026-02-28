"""
Cron job management for scheduled agent tasks.

Stores jobs in PostgreSQL and executes them with full agent context.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import get_connection

# Setup logging
LOGS_DIR = Path(__file__).resolve().parents[2] / "logs" / "cron"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("cron")
logger.setLevel(logging.DEBUG)

# File handler for cron logs
file_handler = logging.FileHandler(LOGS_DIR / "cron.log")
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Also log to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def create_cron_job(
    name: str,
    instructions: str,
    schedule_days: list[int] | None = None,
    schedule_time: str | None = None,
    timezone: str = "America/New_York",
    description: str | None = None,
    created_by: str = "user",
    run_date: str | None = None,
) -> dict[str, Any]:
    """
    Create a new cron job.
    
    Args:
        name: Job name
        instructions: Instructions/prompt for the agent
        schedule_days: List of days (0=Monday, 6=Sunday) - for recurring jobs
        schedule_time: Time in "HH:MM AM/PM" format (e.g., "7:00 PM") - for recurring jobs
        timezone: Timezone for the schedule
        description: Optional description
        created_by: "user" or "agent"
        run_date: Specific date for one-time job (YYYY-MM-DD format)
    
    Returns:
        The created job dict
    """
    is_one_time = run_date is not None
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cron_jobs 
                (name, description, instructions, timezone, schedule_days, schedule_time, run_date, is_one_time, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (name, description, instructions, timezone, schedule_days, schedule_time, run_date, is_one_time, created_by),
            )
            row = cur.fetchone()
    
    job = dict(row) if row else None
    job_type = "one-time" if is_one_time else "recurring"
    logger.info(f"Created {job_type} cron job: {name} (id={job['id'] if job else 'unknown'})")
    return job


def get_cron_job(job_id: int) -> dict[str, Any] | None:
    """Get a single cron job by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cron_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def list_cron_jobs(status: str | None = None) -> list[dict[str, Any]]:
    """
    List all cron jobs, ordered by newest first.
    
    Args:
        status: Filter by status ('active', 'paused', or None for all)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM cron_jobs WHERE status = %s ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM cron_jobs ORDER BY created_at DESC")
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def update_cron_job(
    job_id: int,
    **kwargs,
) -> dict[str, Any] | None:
    """
    Update a cron job.
    
    Allowed fields: name, description, instructions, timezone, schedule_days, schedule_time, run_date, status
    """
    allowed_fields = {
        "name", "description", "instructions", "timezone", 
        "schedule_days", "schedule_time", "run_date", "status"
    }
    
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return get_cron_job(job_id)
    
    set_clause = ", ".join(f"{k} = %s" for k in updates.keys())
    values = list(updates.values()) + [job_id]
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE cron_jobs 
                SET {set_clause}, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                values,
            )
            row = cur.fetchone()
    
    job = dict(row) if row else None
    if job:
        logger.info(f"Updated cron job: {job['name']} (id={job_id})")
    return job


def delete_cron_job(job_id: int) -> bool:
    """Delete a cron job."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cron_jobs WHERE id = %s RETURNING id", (job_id,))
            row = cur.fetchone()
    
    deleted = row is not None
    if deleted:
        logger.info(f"Deleted cron job id={job_id}")
    return deleted


def pause_cron_job(job_id: int) -> dict[str, Any] | None:
    """Pause a cron job."""
    return update_cron_job(job_id, status="paused")


def resume_cron_job(job_id: int) -> dict[str, Any] | None:
    """Resume a paused cron job."""
    return update_cron_job(job_id, status="active")


def record_run(
    job_id: int,
    status: str,
    error: str | None = None,
) -> None:
    """Record a job run result."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cron_jobs 
                SET last_run_at = NOW(),
                    last_run_status = %s,
                    last_run_error = %s,
                    run_count = run_count + 1
                WHERE id = %s
                """,
                (status, error, job_id),
            )
    
    if status == "error" and error:
        logger.error(f"Cron job {job_id} failed: {error}")
    else:
        logger.info(f"Cron job {job_id} completed with status: {status}")


def clone_cron_job(job_id: int, new_name: str | None = None) -> dict[str, Any] | None:
    """Clone an existing cron job."""
    original = get_cron_job(job_id)
    if not original:
        return None
    
    name = new_name or f"{original['name']} (Copy)"
    
    return create_cron_job(
        name=name,
        instructions=original["instructions"],
        schedule_days=original["schedule_days"],
        schedule_time=original["schedule_time"],
        timezone=original["timezone"],
        description=original.get("description"),
        created_by="user",  # Cloned jobs are always user-created
    )


# Common timezones for the dropdown
COMMON_TIMEZONES = [
    ("America/New_York", "Eastern Time (ET)"),
    ("America/Chicago", "Central Time (CT)"),
    ("America/Denver", "Mountain Time (MT)"),
    ("America/Los_Angeles", "Pacific Time (PT)"),
    ("America/Anchorage", "Alaska Time (AKT)"),
    ("Pacific/Honolulu", "Hawaii Time (HT)"),
    ("Europe/London", "Greenwich Mean Time (GMT)"),
    ("Europe/Paris", "Central European Time (CET)"),
    ("Europe/Athens", "Eastern European Time (EET)"),
    ("Asia/Tokyo", "Japan Standard Time (JST)"),
    ("Asia/Shanghai", "China Standard Time (CST)"),
    ("Asia/Dubai", "Gulf Standard Time (GST)"),
    ("Australia/Sydney", "Australian Eastern Time (AET)"),
    ("Pacific/Auckland", "New Zealand Time (NZT)"),
    ("UTC", "UTC"),
]


def get_timezone_display(tz_name: str) -> str:
    """Get display name for a timezone."""
    for tz, display in COMMON_TIMEZONES:
        if tz == tz_name:
            return display
    return tz_name


# Day names for display
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_days(days: list[int]) -> str:
    """Format day list as readable string."""
    if len(days) == 7:
        return "Every day"
    if len(days) == 5 and set(days) == {0, 1, 2, 3, 4}:
        return "Weekdays"
    if len(days) == 2 and set(days) == {5, 6}:
        return "Weekends"
    return ", ".join(DAY_NAMES[d] for d in sorted(days))
