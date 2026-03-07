"""
LangChain tools for the Knowledge Bank (RAG).
"""
from __future__ import annotations

from langchain_core.tools import tool

from .knowledge_bank import is_configured, search as kb_search, list_files as kb_list_files, get_file_content as kb_get_file_content


@tool
def list_knowledge_bank(search_query: str = "") -> str:
    """
    List all documents in the Knowledge Bank (uploaded PDFs, TXT, DOCX, PPTX, MD files).

    ALWAYS call this first when:
    - The user says they uploaded a document, file, or PDF
    - The user asks you to look something up in their documents
    - You are not sure what documents exist
    - A search_knowledge_bank call returns nothing

    Returns each document's filename, tags, chunk count, and upload date.
    Use the exact filename and tags from this list when calling search_knowledge_bank.

    Args:
        search_query: Optional filter — returns only files whose name or tags contain
                      this string. Leave empty to list ALL files.
    """
    if not is_configured():
        return "Knowledge Bank is not configured (KNOWLEDGE_DATABASE_URL not set)."
    files = kb_list_files(search_query or None)
    if not files:
        if search_query:
            return f"No documents found matching '{search_query}' in the Knowledge Bank."
        return "The Knowledge Bank is empty — no documents have been uploaded yet."
    lines = [f"Knowledge Bank — {len(files)} document(s):\n"]
    for f in files:
        tags = ", ".join(f["tags"]) if f["tags"] else "no tags"
        uploaded = (f["uploaded_at"] or "")[:10]
        lines.append(
            f"  [{f['id']}] {f['filename']}  |  tags: {tags}  |  {f['chunk_count']} chunks  |  uploaded {uploaded}"
        )
    return "\n".join(lines)


@tool
def search_knowledge_bank(
    query: str,
    filename_filter: str = "",
    tags: str = "",
    max_chunks: int = 8,
) -> str:
    """
    Search the Knowledge Bank for relevant content from uploaded documents.

    WHEN TO USE:
    - User asks about something that may be in a document they uploaded
    - User says "look it up", "check my notes", "what did the doc say about X"
    - You know the filename or tags from list_knowledge_bank — use them to narrow the search

    HOW TO USE EFFECTIVELY:
    1. Call list_knowledge_bank first to see what files exist and get exact filenames/tags
    2. Pass filename_filter and/or tags to target a specific document — this is MUCH more
       reliable than relying on semantic matching alone when you know the document name
    3. Use a descriptive query about the CONTENT you want, not just the filename

    Args:
        query: What you want to find — describe the topic or content
               (e.g. "Q4 revenue figures", "healing rotation tips", "installation steps")
        filename_filter: Partial filename to restrict search to one document
                         (e.g. "strategy guide" matches "WoW Strategy Guide v2.pdf").
                         Leave empty to search all documents.
        tags: Comma-separated tags to filter by (e.g. "wow,gaming").
              Leave empty to search all documents.
        max_chunks: Number of text chunks to return (default 8, increase if needed).
    """
    if not is_configured():
        return "Knowledge Bank is not configured (KNOWLEDGE_DATABASE_URL not set)."

    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    results = kb_search(
        query,
        max_chunks=max_chunks,
        filename_filter=filename_filter or None,
        tags=tags_list,
    )
    if not results:
        hint = ""
        if not filename_filter and not tags:
            hint = " Try calling list_knowledge_bank to see what documents are available, then search again with filename_filter or tags."
        return f"No relevant content found in the Knowledge Bank.{hint}"

    parts = []
    for r in results:
        parts.append(f"[{r['filename']}  chunk {r['chunk_index']}]\n{r['content']}")
    return "\n\n---\n\n".join(parts)


@tool
def read_knowledge_bank_file(file_id: int, max_words: int = 6000) -> str:
    """
    Read the contents of a Knowledge Bank document by its file ID.

    Use this when:
    - The user asks you to read, summarize, or analyse an entire document
    - search_knowledge_bank returned partial results and you need more context
    - The document is short (≤20 chunks) and you want to read it completely

    Get the file_id from list_knowledge_bank first (shown in brackets, e.g. [14]).

    If the document exceeds max_words, the first max_words words are returned with a
    truncation notice. Use search_knowledge_bank(filename_filter=...) to find specific
    sections beyond the truncation point.

    Args:
        file_id: The numeric file ID from list_knowledge_bank (e.g. 14).
        max_words: Maximum words to return (default 6000). Increase if you need more
                   context, but be mindful of context window limits.
    """
    if not is_configured():
        return "Knowledge Bank is not configured (KNOWLEDGE_DATABASE_URL not set)."
    content = kb_get_file_content(file_id)
    if content is None:
        return f"No file found with id={file_id}. Call list_knowledge_bank to see valid IDs."

    words = content.split()
    total_words = len(words)
    truncated = total_words > max_words

    if truncated:
        content = " ".join(words[:max_words])

    header = f"[File id={file_id} — {total_words} words total"
    if truncated:
        header += f", showing first {max_words} words"
    header += "]\n\n"

    result = header + content
    if truncated:
        result += (
            f"\n\n[TRUNCATED — {total_words - max_words} words remaining. "
            f"Use search_knowledge_bank with filename_filter to find specific sections, "
            f"or call read_knowledge_bank_file(file_id={file_id}, max_words={max_words * 2}) "
            f"to read more.]"
        )
    return result
