"""
Cron / scheduler tools: schedule recurring tasks (e.g. heartbeat).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool


def _get_python_path() -> str:
    """Path to current Python executable."""
    return sys.executable


def _get_heartbeat_command() -> str:
    """Full command to run heartbeat. Ensures correct working directory."""
    python = _get_python_path()
    project_root = Path(__file__).resolve().parents[2]
    if os.name == "nt":
        # Windows: cd to project root so -m src.agent.heartbeat resolves
        return f'cmd /c "cd /d {project_root} && "{python}" -m src.agent.heartbeat"'
    return f'cd {project_root} && {python} -m src.agent.heartbeat'


def cron_schedule_heartbeat(interval_minutes: int = 60) -> str:
    """
    Schedule the heartbeat to run every N minutes via Windows Task Scheduler.

    Creates a task named "AgentHeartbeat" that runs the heartbeat script.
    On non-Windows, returns instructions for manual cron setup.

    Returns success/error message.
    """
    interval_minutes = max(1, min(interval_minutes, 1440))  # 1 min to 24h
    task_name = "AgentHeartbeat"
    cmd = _get_heartbeat_command()

    if os.name == "nt":
        # Windows: schtasks
        try:
            result = subprocess.run(
                [
                    "schtasks",
                    "/create",
                    "/tn", task_name,
                    "/tr", cmd,
                    "/sc", "minute",
                    "/mo", str(interval_minutes),
                    "/f",  # overwrite if exists
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return f"Scheduled heartbeat every {interval_minutes} minutes. Task: {task_name}. To remove: schtasks /delete /tn {task_name}"
            return f"schtasks failed: {result.stderr or result.stdout}"
        except Exception as e:
            return f"Failed to schedule: {e}"
    else:
        # Linux/Mac: crontab
        return (
            f"Heartbeat not auto-scheduled on this OS. To run every {interval_minutes} min, add to crontab:\n"
            f"*/{interval_minutes} * * * * {cmd}\n"
            f"Run: crontab -e"
        )


def cron_remove_heartbeat() -> str:
    """Remove the scheduled heartbeat task."""
    task_name = "AgentHeartbeat"
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", task_name, "/f"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return f"Removed task {task_name}"
            return f"Failed: {result.stderr or result.stdout}"
        except Exception as e:
            return f"Failed: {e}"
    return f"On Linux/Mac, remove the heartbeat line from crontab (crontab -e)"


@tool
def cron_schedule_heartbeat_tool(interval_minutes: int = 60) -> str:
    """
    Schedule the heartbeat to run automatically every N minutes.

    The heartbeat wakes the agent for autonomous time: reflect on memories,
    work on personal projects, reach out to the user if needed, etc. Full autonomy.

    Args:
        interval_minutes: How often to run (default 60). Range 1–1440.
    """
    return cron_schedule_heartbeat(interval_minutes)


@tool
def cron_remove_heartbeat_tool() -> str:
    """Remove the scheduled heartbeat task."""
    return cron_remove_heartbeat()


# ==================== DASHBOARD CRON JOB TOOLS ====================
# These tools manage the APScheduler-based cron jobs stored in PostgreSQL.
# Separate from the Windows Task Scheduler heartbeat tools above.


@tool
def cron_list_jobs_tool(status: str = "") -> str:
    """
    List all scheduled cron jobs in the dashboard.

    Args:
        status: Filter by "active", "paused", or "" for all jobs
    """
    from .cron_jobs import list_cron_jobs, format_days

    status_filter = status.strip() or None
    jobs = list_cron_jobs(status=status_filter)

    if not jobs:
        return "No cron jobs found."

    lines = []
    for job in jobs:
        if job.get("is_one_time"):
            schedule_str = f"One-time on {job.get('run_date')} at {job.get('schedule_time', 'N/A')}"
        else:
            days_str = format_days(job.get("schedule_days") or [])
            schedule_str = f"{days_str} at {job.get('schedule_time', 'N/A')} ({job.get('timezone', 'UTC')})"

        instructions_preview = (job.get("instructions") or "")[:120]
        if len(job.get("instructions") or "") > 120:
            instructions_preview += "..."

        lines.append(
            f"[id={job['id']}] {job['name']} — {job['status'].upper()}\n"
            f"  Schedule: {schedule_str}\n"
            f"  Instructions: {instructions_preview}\n"
            f"  Last run: {job.get('last_run_at') or 'Never'} ({job.get('last_run_status') or 'N/A'})"
        )

    return "\n\n".join(lines)


@tool
def cron_create_job_tool(
    name: str,
    instructions: str,
    schedule_time: str = "12:00 PM",
    schedule_days: list = [],
    timezone: str = "America/New_York",
    description: str = "",
    run_date: str = "",
) -> str:
    """
    Create a new dashboard cron job (scheduled agent task).

    For RECURRING jobs: provide schedule_days and schedule_time.
    For ONE-TIME jobs: provide run_date (YYYY-MM-DD) and schedule_time; leave schedule_days empty.

    Args:
        name: Short descriptive job name
        instructions: What the agent should do when this job runs (the full prompt)
        schedule_time: Time to run, e.g. "7:00 PM" or "9:00 AM" (default "12:00 PM")
        schedule_days: Days to run — 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun.
                       e.g. [0,1,2,3,4] for weekdays. Leave empty [] for one-time jobs.
        timezone: Timezone string (default "America/New_York")
        description: Optional human-readable description
        run_date: For one-time jobs: date in YYYY-MM-DD format. Leave "" for recurring.
    """
    from .cron_jobs import create_cron_job
    from .cron_scheduler import refresh_job_in_scheduler

    try:
        job = create_cron_job(
            name=name,
            instructions=instructions,
            schedule_days=schedule_days if schedule_days else None,
            schedule_time=schedule_time,
            timezone=timezone,
            description=description or None,
            created_by="agent",
            run_date=run_date or None,
        )

        if job:
            refresh_job_in_scheduler(job["id"])
            job_type = "one-time" if job.get("is_one_time") else "recurring"
            return f"Created {job_type} cron job '{name}' (id={job['id']}). It is now scheduled."
        return "Failed to create cron job."
    except Exception as e:
        return f"Error creating cron job: {e}"


@tool
def cron_update_job_tool(
    job_id: int,
    name: str = "",
    instructions: str = "",
    schedule_time: str = "",
    schedule_days: list = [],
    timezone: str = "",
    description: str = "",
    run_date: str = "",
    status: str = "",
) -> str:
    """
    Update an existing dashboard cron job. Only provide the fields you want to change.

    Args:
        job_id: ID of the job to update (get from cron_list_jobs_tool)
        name: New name (omit to keep current)
        instructions: New instructions/prompt (omit to keep current)
        schedule_time: New time e.g. "8:00 AM" (omit to keep current)
        schedule_days: New days list e.g. [0,1,2,3,4] (omit to keep current)
        timezone: New timezone (omit to keep current)
        description: New description (omit to keep current)
        run_date: New run date for one-time jobs YYYY-MM-DD (omit to keep current)
        status: "active" or "paused" (omit to keep current)
    """
    from .cron_jobs import update_cron_job
    from .cron_scheduler import refresh_job_in_scheduler

    kwargs = {}
    if name:
        kwargs["name"] = name
    if instructions:
        kwargs["instructions"] = instructions
    if schedule_days:
        kwargs["schedule_days"] = schedule_days
    if schedule_time:
        kwargs["schedule_time"] = schedule_time
    if timezone:
        kwargs["timezone"] = timezone
    if description:
        kwargs["description"] = description
    if run_date:
        kwargs["run_date"] = run_date
    if status:
        kwargs["status"] = status

    if not kwargs:
        return "No fields provided to update."

    try:
        job = update_cron_job(job_id, **kwargs)
        if job:
            refresh_job_in_scheduler(job_id)
            return f"Updated cron job '{job['name']}' (id={job_id}). Changes are live."
        return f"Job {job_id} not found."
    except Exception as e:
        return f"Error updating cron job: {e}"


@tool
def cron_delete_job_tool(job_id: int) -> str:
    """
    Permanently delete a dashboard cron job.

    Args:
        job_id: ID of the job to delete (get from cron_list_jobs_tool)
    """
    from .cron_jobs import delete_cron_job
    from .cron_scheduler import remove_job_from_scheduler

    try:
        remove_job_from_scheduler(job_id)
        deleted = delete_cron_job(job_id)
        if deleted:
            return f"Deleted cron job {job_id}."
        return f"Job {job_id} not found."
    except Exception as e:
        return f"Error deleting cron job: {e}"


@tool
def cron_pause_job_tool(job_id: int) -> str:
    """
    Pause a dashboard cron job (stops it from running without deleting it).

    Args:
        job_id: ID of the job to pause
    """
    from .cron_jobs import pause_cron_job
    from .cron_scheduler import refresh_job_in_scheduler

    try:
        job = pause_cron_job(job_id)
        if job:
            refresh_job_in_scheduler(job_id)
            return f"Paused cron job '{job['name']}' (id={job_id})."
        return f"Job {job_id} not found."
    except Exception as e:
        return f"Error pausing cron job: {e}"


@tool
def cron_resume_job_tool(job_id: int) -> str:
    """
    Resume a paused dashboard cron job.

    Args:
        job_id: ID of the job to resume
    """
    from .cron_jobs import resume_cron_job
    from .cron_scheduler import refresh_job_in_scheduler

    try:
        job = resume_cron_job(job_id)
        if job:
            refresh_job_in_scheduler(job_id)
            return f"Resumed cron job '{job['name']}' (id={job_id}). It will run as scheduled."
        return f"Job {job_id} not found."
    except Exception as e:
        return f"Error resuming cron job: {e}"
