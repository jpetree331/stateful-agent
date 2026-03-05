"""
Notes boards and items (sticky notes, checklists) for the dashboard.

Stored in PostgreSQL. AI can read and update; only user can delete.
Deleted non-empty items are archived to notes_deleted_items; empty items are removed.
"""
from __future__ import annotations

import re

from .db import get_connection
from psycopg.types.json import Jsonb


def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _is_item_empty(content: dict | None, item_type: str) -> bool:
    """
    Return True if the item has no meaningful content — do not archive when deleted.
    """
    content = content or {}
    if item_type == "note":
        html = content.get("html", "")
        title = (content.get("title") or "").strip()
        text = _strip_html(html)
        return not text and not title
    # checklist
    items = content.get("items") or []
    title = (content.get("title") or "").strip()
    if title:
        return False
    if not items:
        return True
    for it in items:
        if (it.get("text") or "").strip():
            return False
    return True


def list_boards() -> list[dict]:
    """List all notes boards, ordered by sort_order."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, sort_order, created_at, updated_at
                FROM notes_boards
                ORDER BY sort_order ASC, id ASC
                """
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "sort_order": r["sort_order"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


def create_board(name: str) -> dict | None:
    """Create a new notes board."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM notes_boards"
            )
            row = cur.fetchone()
            sort_order = row["next_order"] if row else 0
            cur.execute(
                """
                INSERT INTO notes_boards (name, sort_order)
                VALUES (%s, %s)
                RETURNING id, name, sort_order, created_at, updated_at
                """,
                (name, sort_order),
            )
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "name": r["name"],
        "sort_order": r["sort_order"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def get_board(board_id: int) -> dict | None:
    """Get a single board by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, sort_order, created_at, updated_at FROM notes_boards WHERE id = %s",
                (board_id,),
            )
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "name": r["name"],
        "sort_order": r["sort_order"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def update_board(board_id: int, name: str) -> dict | None:
    """Rename a board."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notes_boards
                SET name = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, sort_order, created_at, updated_at
                """,
                (name, board_id),
            )
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "name": r["name"],
        "sort_order": r["sort_order"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def delete_board(board_id: int) -> bool:
    """Delete a board and all its items. User-only."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notes_boards WHERE id = %s", (board_id,))
            return cur.rowcount > 0


def list_items(board_id: int) -> list[dict]:
    """List all items on a board."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, board_id, item_type, content, position, size,
                       background_color, header_color, created_at, updated_at
                FROM notes_items
                WHERE board_id = %s
                ORDER BY id ASC
                """,
                (board_id,),
            )
            rows = cur.fetchall()
    return [_row_to_item(r) for r in rows]


def _row_to_item(r) -> dict:
    """Convert DB row to API dict."""
    return {
        "id": r["id"],
        "board_id": r["board_id"],
        "item_type": r["item_type"],
        "content": r["content"] or {},
        "position": r["position"] or {"x": 0, "y": 0},
        "size": r["size"] or {"width": 200, "height": 180},
        "background_color": r["background_color"] or "#fef08a",
        "header_color": r["header_color"] or "#eab308",
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def create_item(
    board_id: int,
    item_type: str,
    *,
    content: dict | None = None,
    position: dict | None = None,
    size: dict | None = None,
    background_color: str = "#fef08a",
    header_color: str = "#eab308",
) -> dict | None:
    """Create a new note or checklist item."""
    if item_type not in ("note", "checklist"):
        return None
    content = content or ({"html": ""} if item_type == "note" else {"items": []})
    position = position or {"x": 0, "y": 0}
    size = size or {"width": 200, "height": 180}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notes_items
                (board_id, item_type, content, position, size, background_color, header_color)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, board_id, item_type, content, position, size,
                          background_color, header_color, created_at, updated_at
                """,
                (board_id, item_type, Jsonb(content), Jsonb(position), Jsonb(size), background_color, header_color),
            )
            r = cur.fetchone()
    if not r:
        return None
    return _row_to_item(r)


def get_item(item_id: int) -> dict | None:
    """Get a single item by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, board_id, item_type, content, position, size,
                       background_color, header_color, created_at, updated_at
                FROM notes_items
                WHERE id = %s
                """,
                (item_id,),
            )
            r = cur.fetchone()
    if not r:
        return None
    return _row_to_item(r)


def update_item(
    item_id: int,
    *,
    item_type: str | None = None,
    content: dict | None = None,
    position: dict | None = None,
    size: dict | None = None,
    background_color: str | None = None,
    header_color: str | None = None,
) -> dict | None:
    """Update an item. AI can use this; no delete."""
    updates = []
    params = []
    if item_type is not None:
        updates.append("item_type = %s")
        params.append(item_type)
    if content is not None:
        # Merge into existing content so partial updates (e.g. { html }) don't erase title
        existing = get_item(item_id)
        if existing and existing.get("content"):
            merged = dict(existing["content"])
            merged.update(content)
            content = merged
        updates.append("content = %s")
        params.append(Jsonb(content))
    if position is not None:
        updates.append("position = %s")
        params.append(Jsonb(position))
    if size is not None:
        updates.append("size = %s")
        params.append(Jsonb(size))
    if background_color is not None:
        updates.append("background_color = %s")
        params.append(background_color)
    if header_color is not None:
        updates.append("header_color = %s")
        params.append(header_color)
    if not updates:
        return get_item(item_id)

    params.append(item_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE notes_items
                SET {", ".join(updates)}, updated_at = NOW()
                WHERE id = %s
                RETURNING id, board_id, item_type, content, position, size,
                          background_color, header_color, created_at, updated_at
                """,
                params,
            )
            r = cur.fetchone()
    if not r:
        return None
    return _row_to_item(r)


def _deleted_title_or_preview(content: dict | None, item_type: str) -> str:
    """Get title or initial words for a deleted item."""
    content = content or {}
    title = (content.get("title") or "").strip()
    if title:
        return title
    if item_type == "note":
        html = content.get("html", "")
        text = _strip_html(html)
    elif item_type == "checklist":
        items = content.get("items") or []
        parts = [(it.get("text") or "").strip() for it in items if (it.get("text") or "").strip()]
        text = " ".join(parts)
    else:
        text = _strip_html(content.get("html", "")) or (content.get("markdown") or "")
    return (text[:60] + "…") if len(text) > 60 else text or "(empty)"


def list_deleted_items(
    board_id: int,
    *,
    period: str = "week",
    page: int = 0,
) -> dict:
    """
    List deleted items for a board with pagination by week or month.
    Returns { items, has_more, period, page, window_start, window_end }.
    Items sorted by deleted_at DESC (most recent deletion first).
    page 0 = most recent week/month, page 1 = previous, etc.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    now = datetime.now(tz)
    if period == "month":
        # page 0 = current month, page 1 = last month, ...
        month_offset = page
        y, m = now.year, now.month
        for _ in range(month_offset):
            m -= 1
            if m < 1:
                m = 12
                y -= 1
        window_start = datetime(y, m, 1, tzinfo=tz)
        if m == 12:
            window_end = datetime(y + 1, 1, 1, tzinfo=tz)
        else:
            window_end = datetime(y, m + 1, 1, tzinfo=tz)
    else:
        # page 0 = this week (Mon-Sun), page 1 = last week, ...
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = week_start + timedelta(days=7 * (1 - page))
        window_start = week_start - timedelta(days=7 * page)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, board_id, item_type, content, position, size,
                       background_color, header_color, created_at, deleted_at
                FROM notes_deleted_items
                WHERE board_id = %s
                  AND deleted_at >= %s AND deleted_at < %s
                ORDER BY deleted_at DESC, created_at DESC
                LIMIT 101
                """,
                (board_id, window_start, window_end),
            )
            rows = cur.fetchall()
    items = []
    for r in rows[:100]:
        content = r.get("content") or {}
        items.append({
            "id": r["id"],
            "board_id": r["board_id"],
            "item_type": r["item_type"],
            "title_or_preview": _deleted_title_or_preview(content, r["item_type"]),
            "content": content,
            "position": r["position"] or {"x": 0, "y": 0},
            "size": r["size"] or {"width": 200, "height": 180},
            "background_color": r["background_color"] or "#fef08a",
            "header_color": r["header_color"] or "#eab308",
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "deleted_at": r["deleted_at"].isoformat() if r["deleted_at"] else None,
        })
    return {
        "items": items,
        "has_more": len(rows) > 100,
        "period": period,
        "page": page,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }


def get_deleted_pages_info(board_id: int) -> dict:
    """Get available week/month ranges for pagination."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MIN(deleted_at) AS first, MAX(deleted_at) AS last
                FROM notes_deleted_items
                WHERE board_id = %s
                """,
                (board_id,),
            )
            r = cur.fetchone()
    if not r or not r["first"]:
        return {"weeks": 0, "months": 0}
    first = r["first"]
    last = r["last"]
    if isinstance(first, str):
        first = datetime.fromisoformat(first.replace("Z", "+00:00")).astimezone(tz)
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(tz)
    weeks = max(0, (last - first).days // 7 + 1)
    months = max(0, (last.year - first.year) * 12 + (last.month - first.month) + 1)
    return {"weeks": weeks, "months": months}


def restore_deleted_item(deleted_id: int, board_id: int | None = None) -> dict | None:
    """
    Restore a deleted item back to its board.
    Copies from notes_deleted_items to notes_items, then removes from deleted.
    If board_id is given, verifies the deleted item belongs to that board.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT board_id, item_type, content, position, size,
                       background_color, header_color
                FROM notes_deleted_items
                WHERE id = %s
                """,
                (deleted_id,),
            )
            r = cur.fetchone()
    if not r:
        return None
    if board_id is not None and r["board_id"] != board_id:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notes_items
                    (board_id, item_type, content, position, size, background_color, header_color)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, board_id, item_type, content, position, size,
                          background_color, header_color, created_at, updated_at
                """,
                (
                    r["board_id"],
                    r["item_type"],
                    Jsonb(r["content"] or {}),
                    Jsonb(r["position"] or {"x": 0, "y": 0}),
                    Jsonb(r["size"] or {"width": 200, "height": 180}),
                    r["background_color"] or "#fef08a",
                    r["header_color"] or "#eab308",
                ),
            )
            new_row = cur.fetchone()
            cur.execute("DELETE FROM notes_deleted_items WHERE id = %s", (deleted_id,))
    if not new_row:
        return None
    return _row_to_item(new_row)


def delete_item(item_id: int) -> bool:
    """
    Delete an item. User-only (AI cannot delete).
    Non-empty items are archived to notes_deleted_items before removal.
    Empty items are removed without archiving.
    """
    item = get_item(item_id)
    if not item:
        return False

    with get_connection() as conn:
        with conn.cursor() as cur:
            if not _is_item_empty(item.get("content"), item.get("item_type", "note")):
                # Archive to deleted notes (preserve created_at, record deleted_at)
                cur.execute(
                    """
                    INSERT INTO notes_deleted_items
                    (original_id, board_id, item_type, content, position, size,
                     background_color, header_color, created_at, deleted_at)
                    SELECT id, board_id, item_type, content, position, size,
                           background_color, header_color, created_at, NOW()
                    FROM notes_items
                    WHERE id = %s
                    """,
                    (item_id,),
                )
            cur.execute("DELETE FROM notes_items WHERE id = %s", (item_id,))
            return cur.rowcount > 0


# === Finished items (moved from checklist when done) ===

def list_finished_items(board_id: int) -> list[dict]:
    """List finished items for a board."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, board_id, text, finished_at, source_checklist_id, created_at
                FROM notes_finished_items
                WHERE board_id = %s
                ORDER BY finished_at DESC
                """,
                (board_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "board_id": r["board_id"],
            "text": r["text"],
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "source_checklist_id": r["source_checklist_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def add_finished_item(
    board_id: int,
    text: str,
    *,
    source_checklist_id: int | None = None,
) -> dict | None:
    """Add a finished item (moved from checklist)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notes_finished_items (board_id, text, source_checklist_id)
                VALUES (%s, %s, %s)
                RETURNING id, board_id, text, finished_at, source_checklist_id, created_at
                """,
                (board_id, text, source_checklist_id),
            )
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "board_id": r["board_id"],
        "text": r["text"],
        "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        "source_checklist_id": r["source_checklist_id"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


def archive_finished_item(board_id: int, finished_id: int) -> bool:
    """Move a finished item to archive (hidden from user, AI can read)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notes_archived_items (board_id, text, finished_at, source_checklist_id)
                SELECT board_id, text, finished_at, source_checklist_id
                FROM notes_finished_items
                WHERE id = %s AND board_id = %s
                """,
                (finished_id, board_id),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                "DELETE FROM notes_finished_items WHERE id = %s AND board_id = %s",
                (finished_id, board_id),
            )
            return cur.rowcount > 0


# Board name that is invisible to the AI (private reflections)
PRIVATE_BOARD_NAME = "Private"


def _get_private_board_id() -> int | None:
    """Return the board id for 'Private', or None if it doesn't exist."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM notes_boards WHERE name = %s LIMIT 1", (PRIVATE_BOARD_NAME,))
            row = cur.fetchone()
            return row["id"] if row else None


def list_archived_items(board_id: int | None = None, limit: int = 100) -> list[dict]:
    """List archived items (for AI). board_id optional."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if board_id is not None:
                cur.execute(
                    """
                    SELECT id, board_id, text, finished_at, archived_at, source_checklist_id, created_at
                    FROM notes_archived_items
                    WHERE board_id = %s
                    ORDER BY archived_at DESC
                    LIMIT %s
                    """,
                    (board_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, board_id, text, finished_at, archived_at, source_checklist_id, created_at
                    FROM notes_archived_items
                    ORDER BY archived_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "board_id": r["board_id"],
            "text": r["text"],
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "archived_at": r["archived_at"].isoformat() if r["archived_at"] else None,
            "source_checklist_id": r["source_checklist_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
