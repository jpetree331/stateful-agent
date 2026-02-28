"""
File system tools: read, write, list, search, and safely trash files.

No hard delete. Items the agent marks for deletion go to a trash folder
(default: ~/Desktop/Agent_Trash) where the user can review and manually delete them.
A .reason.txt file is written alongside each trashed item explaining why.

Env vars:
  AGENT_TRASH_FOLDER — path to trash folder (default: ~/Desktop/Agent_Trash)
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

_TRASH_FOLDER = Path(
    os.environ.get("AGENT_TRASH_FOLDER", str(Path.home() / "Desktop" / "Agent_Trash"))
)
_MAX_READ_CHARS = 50_000  # truncate very large files for context safety


def _ensure_trash():
    _TRASH_FOLDER.mkdir(parents=True, exist_ok=True)


@tool
def read_file(path: str) -> str:
    """
    Read and return the full text contents of a file.

    Use to read documents, code files, notes, config files, logs, or any text file.
    Large files are truncated at 50,000 characters with a notice.

    Args:
        path: Absolute or relative path to the file (~ is expanded).
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: not found — {p}"
        if not p.is_file():
            return f"Error: not a file — {p}"
        content = p.read_text(encoding="utf-8", errors="replace")
        size_kb = p.stat().st_size / 1024
        truncated = ""
        if len(content) > _MAX_READ_CHARS:
            content = content[:_MAX_READ_CHARS]
            truncated = f"\n\n[... truncated — file is {size_kb:.0f} KB, showing first {_MAX_READ_CHARS:,} chars]"
        return f"[{p} | {size_kb:.1f} KB]\n\n{content}{truncated}"
    except Exception as e:
        return f"Error reading {path}: {e}"


@tool
def write_file(path: str, content: str, mode: str = "write") -> str:
    """
    Write or append text content to a file, creating it (and any parent dirs) if needed.

    Use to create new files, save notes, write scripts, output reports, or log things.

    Args:
        path: Absolute or relative path to the file (~ is expanded).
        content: Text content to write.
        mode: "write" — create or overwrite (default).
              "append" — add to the end of an existing file.
    """
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "a" if mode == "append" else "w"
        with open(p, open_mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if mode == "append" else "Written"
        return f"{action}: {p} ({len(content):,} chars)"
    except Exception as e:
        return f"Error writing {path}: {e}"


@tool
def list_directory(path: str = "~", show_hidden: bool = False) -> str:
    """
    List the contents of a directory, showing files and subfolders with sizes and dates.

    Use to browse the file system, find what's in a folder, or navigate the PC.

    Args:
        path: Path to the directory (default: home directory, ~ is expanded).
        show_hidden: Include hidden files/folders that start with '.' (default: False).
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: not found — {p}"
        if not p.is_dir():
            return f"Error: not a directory — {p}"

        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        lines = [f"[{p}]\n"]
        for entry in entries:
            try:
                stat = entry.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                if entry.is_dir():
                    lines.append(f"  📁  {entry.name}/  [{mtime}]")
                else:
                    sz = stat.st_size
                    sz_str = (
                        f"{sz} B" if sz < 1024
                        else f"{sz/1024:.1f} KB" if sz < 1_048_576
                        else f"{sz/1_048_576:.1f} MB"
                    )
                    lines.append(f"  📄  {entry.name}  [{sz_str}, {mtime}]")
            except PermissionError:
                lines.append(f"  ⚠️   {entry.name}  [permission denied]")

        if len(lines) == 1:
            lines.append("  (empty)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing {path}: {e}"


@tool
def move_to_trash(path: str, reason: str) -> str:
    """
    Move a file or folder to the Agent Trash folder instead of permanently deleting it.

    The user reviews the trash folder and decides what to permanently delete.
    A reason file is saved alongside so the decision is documented.

    IMPORTANT: Only use this when you are confident the item is no longer needed
    and can articulate a clear reason. When in doubt, do NOT trash it — ask the user instead.

    Args:
        path: Path to the file or folder to move (~ is expanded).
        reason: Clear explanation of why this should be deleted. Required.
    """
    if not reason or not reason.strip():
        return "Error: a reason is required. Explain why this item should be deleted."
    try:
        src = Path(path).expanduser().resolve()
        if not src.exists():
            return f"Error: not found — {src}"

        _ensure_trash()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = _TRASH_FOLDER / f"{stamp}_{src.name}"

        # Write a reason file documenting why it was trashed
        reason_file = _TRASH_FOLDER / f"{stamp}_{src.name}.reason.txt"
        reason_file.write_text(
            f"Original path: {src}\n"
            f"Trashed at:    {datetime.now().isoformat()}\n"
            f"Reason:        {reason}\n",
            encoding="utf-8",
        )

        shutil.move(str(src), str(dest))
        return (
            f"Moved to trash: {src.name}\n"
            f"Location: {dest}\n"
            f"Reason logged: {reason}"
        )
    except Exception as e:
        return f"Error moving to trash: {e}"


@tool
def search_files(
    pattern: str,
    directory: str = "~",
    search_content: bool = False,
    max_results: int = 20,
) -> str:
    """
    Search for files by name pattern or content keyword across a directory tree.

    Use to find files anywhere on the PC by glob pattern (e.g., "*.py", "report*")
    or to find files containing a specific keyword in their text.

    Args:
        pattern: Glob pattern for filename matching (e.g., "*.txt", "budget*", "*.py").
                 When search_content=True, this is also used as a text keyword inside files.
        directory: Root directory to search from (default: home folder).
                   For a whole-drive search use "C:/" but expect it to be slow.
        search_content: If True, also search inside text files for the pattern as a keyword.
                        Slower but finds files by content, not just name.
        max_results: Maximum number of results to return (default 20).
    """
    try:
        base = Path(directory).expanduser().resolve()
        if not base.exists():
            return f"Error: directory not found — {base}"

        matches: list[str] = []

        # Phase 1: name-based glob search
        try:
            for p in base.rglob(pattern):
                if p.is_file():
                    sz = p.stat().st_size
                    sz_str = f"{sz/1024:.1f} KB" if sz >= 1024 else f"{sz} B"
                    matches.append(f"  {p}  [{sz_str}]")
                if len(matches) >= max_results:
                    break
        except Exception:
            pass

        # Phase 2: content search (text files only, skip if already at limit)
        if search_content and len(matches) < max_results:
            keyword = pattern.replace("*", "").replace("?", "").lower()
            for p in base.rglob("*"):
                if len(matches) >= max_results:
                    break
                if not p.is_file() or p.stat().st_size > 5_000_000:
                    continue
                try:
                    if keyword in p.read_text(encoding="utf-8", errors="ignore").lower():
                        sz_str = f"{p.stat().st_size/1024:.1f} KB"
                        matches.append(f"  {p}  [{sz_str}] (content match)")
                except Exception:
                    pass

        if not matches:
            return f"No files matching '{pattern}' found in {base}."

        header = f"[Search '{pattern}' in {base} — {len(matches)} result(s)]\n"
        return header + "\n".join(matches)
    except Exception as e:
        return f"Error searching: {e}"
