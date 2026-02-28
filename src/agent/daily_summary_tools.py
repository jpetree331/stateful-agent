"""
Daily summary tool: the agent writes a short summary of the day in its own words.
Summaries are stored in PostgreSQL and loaded into context for the past 7 days,
giving persistent temporal context across the sliding message window.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def daily_summary_write(date: str, summary: str) -> str:
    """
    Write or update the daily summary for a specific date.

    Use this at the end of each day (or during a heartbeat) to record what
    happened today — key conversations, tasks completed, things you learned,
    anything worth carrying forward as context for tomorrow.

    This summary is automatically loaded into your context every session,
    so writing a good summary means future-you will remember the shape of the day
    even after specific messages have scrolled out of the context window.

    Args:
        date: The date to summarise in YYYY-MM-DD format (usually today).
        summary: A concise but meaningful summary of the day in your own words.
                 Aim for 3-8 sentences covering key topics, outcomes, and anything
                 you want to remember tomorrow.
    """
    from .db import upsert_daily_summary

    try:
        row = upsert_daily_summary(date, summary)
        return f"Daily summary saved for {row['summary_date']}."
    except Exception as e:
        return f"Error saving daily summary: {e}"
