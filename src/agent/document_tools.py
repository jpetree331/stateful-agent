"""
Document reading tool: PDF and plain-text files.

Handles PDF extraction via pypdf and falls back to plain text reading for
everything else (.txt, .md, .csv, .log, .json, etc.).

Dependencies:
  pypdf>=4.0  (add to requirements.txt)
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

_MAX_CHARS = 80_000  # generous limit; PDFs can be large


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Error: pypdf is not installed. Run: pip install pypdf"

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"--- Page {i} ---\n{text.strip()}")
    return "\n\n".join(pages) if pages else "(No extractable text found in PDF)"


@tool
def read_document(path: str) -> str:
    """
    Read and return the text content of a document — PDF or any plain-text file.

    For PDFs, extracts text page by page. For all other files (.txt, .md, .csv,
    .json, .log, code files, etc.) reads as plain text with UTF-8 encoding.
    Large documents are truncated at 80,000 characters with a notice.

    Use this instead of read_file when working with PDFs. For regular text files
    either tool works, but read_document is preferred for documents you intend to
    read and summarise.

    Args:
        path: Absolute or relative path to the document (~ is expanded).
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: file not found — {p}"
        if not p.is_file():
            return f"Error: not a file — {p}"

        size_kb = p.stat().st_size / 1024
        header = f"[{p.name} | {size_kb:.1f} KB]\n\n"

        if p.suffix.lower() == ".pdf":
            content = _read_pdf(p)
        else:
            content = p.read_text(encoding="utf-8", errors="replace")

        truncated = ""
        if len(content) > _MAX_CHARS:
            content = content[:_MAX_CHARS]
            truncated = f"\n\n[... truncated at {_MAX_CHARS:,} chars — {size_kb:.0f} KB total]"

        return header + content + truncated

    except Exception as e:
        return f"Error reading {path}: {e}"
