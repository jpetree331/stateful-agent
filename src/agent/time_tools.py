"""
Time awareness tools for the agent.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

AGENT_TIMEZONE = ZoneInfo(os.environ.get("AGENT_TIMEZONE", "America/New_York"))


@tool
def get_current_time(timezone: str | None = None) -> str:
    """
    Get the current date and time.
    
    Args:
        timezone: Optional timezone (e.g., "America/New_York", "UTC"). 
                  Defaults to the agent's configured timezone.
    
    Returns:
        Current date and time formatted as a string.
    """
    tz = ZoneInfo(timezone) if timezone else AGENT_TIMEZONE
    now = datetime.now(tz)
    
    return (
        f"Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}\n"
        f"Date: {now.strftime('%Y-%m-%d')}\n"
        f"Time: {now.strftime('%H:%M:%S')}\n"
        f"Timezone: {tz.key if hasattr(tz, 'key') else str(tz)}"
    )


@tool
def get_current_timestamp() -> str:
    """
    Get the current Unix timestamp.
    
    Returns:
        Current Unix timestamp as a string.
    """
    import time
    return str(int(time.time()))


TIME_TOOLS = [get_current_time, get_current_timestamp]
