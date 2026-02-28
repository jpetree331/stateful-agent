"""
Hindsight tools for the agent: recall and reflect.

These access the agent's deep memory — lived experience, not bullet points.
"""
from langchain_core.tools import tool

from .hindsight import HINDSIGHT_BANK_ID, recall, reflect


@tool
def hindsight_recall(query: str) -> str:
    """
    Search your deep memory (Hindsight) for past experiences.

    Use when: the user references a specific past event, project, or detail that is NOT
    in your Core Memory or loaded conversation history. Do not hallucinate — if you
    don't know, use this tool to search your lived experience before replying.

    The results are YOUR recollections — speak from "I" perspective, reference them
    as your own experience.

    Args:
        query: What to search for (e.g., "sci-fi book we discussed", "voice analysis project").
    """
    return recall(HINDSIGHT_BANK_ID, query)


@tool
def hindsight_reflect(query: str) -> str:
    """
    Reflect deeply on your memories — synthesize patterns, insights, and understanding.

    Use when: the user asks deep, relational, or pattern-based questions. Examples:
    - "Do I seem more anxious lately?"
    - "What are our recurring themes when discussing theology?"
    - "How has my worldview evolved?"
    - Self-reflection: "What have I learned about the user's preferences?"

    This goes beyond simple recall — it reasons over your experiences to form new
    connections and insights.

    Args:
        query: The question or theme to reflect on.
    """
    return reflect(HINDSIGHT_BANK_ID, query)
