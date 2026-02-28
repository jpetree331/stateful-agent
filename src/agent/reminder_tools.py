"""
One-shot reminder tool: fire a Windows notification after N minutes.

Uses threading.Timer (built-in) — no external packages or scheduler needed.
Requires the API server (api.py) to remain running while the timer counts down.
For reminders that must survive restarts, use the cron system instead.

When the timer fires, it sends a Windows desktop toast notification. If the
notification fails (e.g. PowerShell unavailable), it logs to the console.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Active reminders: maps timer → description (for introspection if needed)
_active_reminders: dict[threading.Timer, str] = {}
_lock = threading.Lock()


def _fire(message: str, timer: threading.Timer) -> None:
    """Called when the timer expires. Sends a toast and cleans up."""
    with _lock:
        _active_reminders.pop(timer, None)

    # Import here to avoid circular dependency at module load time
    try:
        from .windows_tools import _run_ps
        safe_msg = message.replace('"', "'").replace("`", "'")
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>⏰ Reminder</text><text>{safe_msg}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Stateful Agent').Show($toast)
"""
        _run_ps(ps_script)
    except Exception:
        pass

    logger.info("Reminder fired: %s", message)
    print(f"\n⏰ REMINDER: {message}\n")


@tool
def set_reminder(message: str, minutes: float) -> str:
    """
    Set a one-shot reminder that fires as a Windows desktop notification after N minutes.

    When the time comes, a toast notification pops up on the user's desktop with the message.
    Use for short-to-medium reminders during the current session (e.g. "check the oven in 20 mins").
    For reminders that should persist across restarts, use the cron scheduler instead.

    Requires the API server (api.py) to stay running — timers live in-process.

    Args:
        message: What the reminder should say. Be specific and actionable.
        minutes: How many minutes from now to fire (can be fractional, e.g. 0.5 for 30 seconds).
    """
    if minutes <= 0:
        return "Error: minutes must be greater than 0."
    if minutes > 1440:
        return "Error: reminders over 24 hours aren't reliable in-process. Use a cron job instead."

    seconds = minutes * 60
    due = datetime.now() + timedelta(minutes=minutes)

    # Create a placeholder to pass to the closure (timer refers to itself)
    timer_holder: list[threading.Timer] = []

    def _callback():
        _fire(message, timer_holder[0])

    timer = threading.Timer(seconds, _callback)
    timer_holder.append(timer)
    timer.daemon = True
    timer.start()

    with _lock:
        _active_reminders[timer] = message

    due_str = due.strftime("%I:%M %p")
    return f"Reminder set for {due_str} ({minutes:.0f} min): '{message}'"


@tool
def list_reminders() -> str:
    """
    List all currently pending reminders set in this session.

    Shows the reminder message for each active timer. Note that timers are
    in-process and will be lost if the API server restarts.
    """
    with _lock:
        if not _active_reminders:
            return "No active reminders."
        lines = [f"Active reminders ({len(_active_reminders)}):"]
        for i, msg in enumerate(_active_reminders.values(), 1):
            lines.append(f"  {i}. {msg}")
        return "\n".join(lines)
