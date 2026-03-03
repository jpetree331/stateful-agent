"""
LangChain tools for the Knowledge Bank (RAG).
"""
from __future__ import annotations

from langchain_core.tools import tool

from .knowledge_bank import is_configured, search as kb_search


@tool
def search_knowledge_bank(query: str, max_chunks: int = 5) -> str:
    """
    Search the Knowledge Bank for relevant information from uploaded documents.

    Use this when the user asks about topics that may be covered in documents they've
    uploaded (PDFs, TXT, DOCX, PPTX, MD). Returns semantically relevant chunks with
    source filename. If nothing is found, returns an empty result.

    Args:
        query: Natural language search query (e.g. "What did the report say about Q4 revenue?")
        max_chunks: Maximum number of chunks to return (default 5).
    """
    if not is_configured():
        return "Knowledge Bank is not configured (KNOWLEDGE_DATABASE_URL not set)."
    results = kb_search(query, max_chunks=max_chunks)
    if not results:
        return "No relevant documents found in the Knowledge Bank."
    parts = []
    for r in results:
        parts.append(f"[{r['filename']}]\n{r['content']}")
    return "\n\n---\n\n".join(parts)
