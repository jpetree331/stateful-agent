"""
Notes tools for the agent.

The agent can read, create, and update notes/checklists on the user's dashboard.
The agent CANNOT delete — only the user can delete notes and boards.
"""
from __future__ import annotations

import re
from langchain_core.tools import tool

from .db import get_connection
from .notes import (
    list_boards,
    list_items,
    create_item,
    get_item,
    update_item,
    get_board,
    list_finished_items,
    list_archived_items,
    PRIVATE_BOARD_NAME,
    _get_private_board_id,
)


def _strip_html(html: str) -> str:
    """Strip HTML tags for plain-text representation."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_item_for_agent(item: dict) -> str:
    """Format a single note/checklist/doc item for agent consumption."""
    content = item.get("content") or {}
    title = (content.get("title") or "").strip()
    parts = [f"[{item['item_type'].upper()}] id={item['id']}" + (f" — {title}" if title else "")]
    if item["item_type"] in ("note", "doc"):
        html = content.get("html", "")
        text = _strip_html(html)
        if text:
            parts.append(f"  Content: {text}")
    else:
        items_list = content.get("items") or []
        for i, it in enumerate(items_list):
            prefix = "[x]" if it.get("checked") else "[ ]"
            text = (it.get("text") or "").strip()
            parts.append(f"  {prefix} {text}")
    return "\n".join(parts)


def _get_all_notes_summary(board_id: int | None = None) -> str:
    """Get a human-readable summary of notes for the agent. Private board is excluded."""
    if board_id is not None:
        board = get_board(board_id)
        if not board:
            return f"Board id={board_id} not found."
        if board["name"] == PRIVATE_BOARD_NAME:
            return "Board not found."

        boards = [board]
    else:
        boards = [b for b in list_boards() if b["name"] != PRIVATE_BOARD_NAME]

    if not boards:
        return "No notes boards found."

    lines = []
    for b in boards:
        items = list_items(b["id"])
        finished = list_finished_items(b["id"])
        archived = list_archived_items(b["id"], limit=50)
        lines.append(f"\n=== Board: {b['name']} (id={b['id']}) ===")
        if not items:
            lines.append("  (empty)")
        else:
            for item in items:
                lines.append(_format_item_for_agent(item))
        if finished:
            lines.append("  --- Finished (done, not yet archived) ---")
            for f in finished:
                lines.append(f"  [FINISHED] {f['text']} (finished {f.get('finished_at', '')})")
        if archived:
            lines.append("  --- Archived (hidden from UI, kept for record) ---")
            for a in archived:
                lines.append(f"  [ARCHIVED] {a['text']} (finished {a.get('finished_at', '')}, archived {a.get('archived_at', '')})")
    return "\n".join(lines).strip()


@tool
def notes_read(board_id: int | None = None) -> str:
    """
    Read all notes and checklists from the user's dashboard.

    Returns a summary of all boards and their items, including finished and archived
    to-do items. Use this when the user asks about notes, tasks, or to-do lists, or when
    you need to reference what they have written.

    Args:
        board_id: Optional. If provided, only return that board's items.
                 If omitted, returns all boards and their items.

    Returns:
        Summary of notes and checklists. Notes show plain text; checklists
        show items with [x] for done and [ ] for pending. Finished and archived
        items are also included.
    """
    return _get_all_notes_summary(board_id)


@tool
def notes_search(query: str, board_id: int | None = None, limit: int = 20) -> str:
    """
    Search notes, finished items, archived items, and deleted notes by keyword.

    Use when the user asks about something specific in their notes, or when you need
    to find items matching a topic. Searches across note content, checklist items,
    finished to-dos, archived items, and soft-deleted notes/checklists.

    Args:
        query: Search term (case-insensitive).
        board_id: Optional. Limit search to a specific board.
        limit: Max results to return (default 20).

    Returns:
        Matching items with context (board name, type, dates).
    """
    query = (query or "").strip()
    if not query:
        return "Please provide a search query."

    pattern = f"%{query}%"
    results = []
    private_id = _get_private_board_id()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Search notes_items (content JSONB); exclude Private board
            cur.execute(
                """
                SELECT ni.id, ni.board_id, nb.name AS board_name, ni.item_type, ni.content, ni.updated_at
                FROM notes_items ni
                JOIN notes_boards nb ON nb.id = ni.board_id
                WHERE (ni.content::text ILIKE %s)
                  AND (%s IS NULL OR ni.board_id = %s)
                  AND (ni.board_id != %s OR %s IS NULL)
                ORDER BY ni.updated_at DESC
                LIMIT %s
                """,
                (pattern, board_id, board_id, private_id, private_id, limit),
            )
            for r in cur.fetchall():
                content = r.get("content") or {}
                if r["item_type"] == "note":
                    text = _strip_html(content.get("html", ""))
                else:
                    items = content.get("items") or []
                    text = " | ".join((it.get("text") or "").strip() for it in items)
                results.append(
                    f"[{r['item_type'].upper()}] Board '{r['board_name']}' id={r['id']}: {text[:200]}..."
                    if len(text) > 200 else f"[{r['item_type'].upper()}] Board '{r['board_name']}' id={r['id']}: {text}"
                )

            # Search finished items; exclude Private board
            cur.execute(
                """
                SELECT nf.id, nf.board_id, nb.name AS board_name, nf.text, nf.finished_at
                FROM notes_finished_items nf
                JOIN notes_boards nb ON nb.id = nf.board_id
                WHERE nf.text ILIKE %s
                  AND (%s IS NULL OR nf.board_id = %s)
                  AND (nf.board_id != %s OR %s IS NULL)
                ORDER BY nf.finished_at DESC
                LIMIT %s
                """,
                (pattern, board_id, board_id, private_id, private_id, limit),
            )
            for r in cur.fetchall():
                results.append(
                    f"[FINISHED] Board '{r['board_name']}': {r['text']} (finished {r['finished_at']})"
                )

            # Search archived items; exclude Private board
            cur.execute(
                """
                SELECT na.id, na.board_id, nb.name AS board_name, na.text, na.finished_at, na.archived_at
                FROM notes_archived_items na
                LEFT JOIN notes_boards nb ON nb.id = na.board_id
                WHERE na.text ILIKE %s
                  AND (%s IS NULL OR na.board_id = %s)
                  AND (na.board_id != %s OR %s IS NULL)
                ORDER BY na.archived_at DESC
                LIMIT %s
                """,
                (pattern, board_id, board_id, private_id, private_id, limit),
            )
            for r in cur.fetchall():
                board_name = r["board_name"] or f"Board {r['board_id']}"
                results.append(
                    f"[ARCHIVED] Board '{board_name}': {r['text']} (archived {r['archived_at']})"
                )

            # Search deleted items (soft-deleted notes/checklists)
            cur.execute(
                """
                SELECT nd.id, nd.board_id, nb.name AS board_name, nd.item_type, nd.content, nd.deleted_at
                FROM notes_deleted_items nd
                LEFT JOIN notes_boards nb ON nb.id = nd.board_id
                WHERE nd.content::text ILIKE %s
                  AND (%s IS NULL OR nd.board_id = %s)
                  AND (nd.board_id != %s OR %s IS NULL)
                ORDER BY nd.deleted_at DESC
                LIMIT %s
                """,
                (pattern, board_id, board_id, private_id, private_id, limit),
            )
            for r in cur.fetchall():
                content = r.get("content") or {}
                if r["item_type"] == "note":
                    text = _strip_html(content.get("html", ""))
                elif r["item_type"] == "checklist":
                    items = content.get("items") or []
                    text = " | ".join((it.get("text") or "").strip() for it in items)
                else:
                    text = _strip_html(content.get("html", "")) or (content.get("markdown") or "")
                board_name = r["board_name"] or f"Board {r['board_id']}"
                preview = (text[:200] + "...") if len(text) > 200 else text
                results.append(
                    f"[DELETED] Board '{board_name}': {preview} (deleted {r['deleted_at']})"
                )

    if not results:
        return f"No notes, finished, archived, or deleted items found matching '{query}'."
    return "\n".join(results[:limit])


@tool
def notes_create(
    board_id: int,
    item_type: str,
    content: str,
    title: str = "",
) -> str:
    """
    Create a new note or checklist item on a board.

    Use when the user asks you to add something to their notes, create a to-do,
    or add a reminder to their board.

    Args:
        board_id: The board ID (from notes_read). Use 1 for General if unsure.
        item_type: Either "note" (plain text) or "checklist" (to-do with checkboxes).
        content: For notes: the text to add. For checklists: newline-separated items,
                e.g. "Buy milk\\nCall dentist\\nFinish report".
        title: Optional header/title for the note or checklist.

    Returns:
        Success message with the new item ID, or an error.
    """
    if item_type not in ("note", "checklist"):
        return "Error: item_type must be 'note' or 'checklist'."

    board = get_board(board_id)
    if not board:
        return f"Error: Board id={board_id} not found."
    if board["name"] == PRIVATE_BOARD_NAME:
        return "Error: Cannot create items on that board."

    if item_type == "note":
        # Simple HTML: wrap in <p> for each paragraph
        html = "".join(f"<p>{line}</p>" for line in content.strip().split("\n") if line.strip())
        if not html:
            html = "<p></p>"
        content_dict = {"html": html, "title": (title or "").strip()}
    else:
        items_list = [
            {"text": line.strip(), "checked": False}
            for line in content.strip().split("\n")
            if line.strip()
        ]
        content_dict = {"items": items_list, "title": (title or "").strip()}

    item = create_item(
        board_id,
        item_type,
        content=content_dict,
        position={"x": 40, "y": 40},
        size={"width": 220, "height": 180} if item_type == "checklist" else {"width": 200, "height": 180},
    )
    if not item:
        return "Error: Failed to create item."
    return f"Created {item_type} id={item['id']} on board '{board['name']}'."


@tool
def notes_update(
    item_id: int,
    content: str,
    title: str | None = None,
) -> str:
    """
    Update a note or checklist item. You can read and update content.

    You CANNOT delete notes — only the user can delete from the dashboard.

    Args:
        item_id: The item ID (from notes_read).
        content: New content. For notes: plain text. For checklists: newline-separated
                items; prefix with [x] for done, [ ] for pending, e.g. "[x] Done item\\n[ ] Todo".
        title: Optional. New title/header for the note or checklist.

    Returns:
        Success message or error.
    """
    item = get_item(item_id)
    if not item:
        return f"Error: Item id={item_id} not found."

    board = get_board(item["board_id"])
    if board and board["name"] == PRIVATE_BOARD_NAME:
        return "Error: Item not found."

    if not content:
        return "No changes provided."

    existing = item.get("content") or {}
    if item["item_type"] == "note":
        html = "".join(f"<p>{line}</p>" for line in content.strip().split("\n") if line.strip())
        if not html:
            html = "<p></p>"
        content_dict = {**existing, "html": html}
    else:
        items_list = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            checked = line.lower().startswith("[x]")
            text = re.sub(r"^\[x\]\s*", "", line, flags=re.IGNORECASE)
            text = re.sub(r"^\[\s*\]\s*", "", text).strip()
            items_list.append({"text": text, "checked": checked})
        content_dict = {**existing, "items": items_list}

    if title is not None:
        content_dict["title"] = title.strip()

    updated = update_item(item_id, content=content_dict)
    if not updated:
        return "Error: Failed to update item."
    return f"Updated {item['item_type']} id={item_id}."
