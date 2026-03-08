"""
Fetch and read webpage content from a URL.

Use when the user shares a link — you can read the page content to understand
what they're referring to.
"""
from __future__ import annotations

import re

import httpx
from langchain_core.tools import tool

_MAX_CHARS = 30_000
_TIMEOUT = 15


def _extract_text_from_html(html: str) -> str:
    """Crude HTML-to-text extraction. Removes tags, decodes entities."""
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@tool
def fetch_url(url: str) -> str:
    """
    Fetch and read the text content of a webpage from a URL.

    Use when the user shares a link and you need to see what's on that page.
    Returns the main text content (stripped of HTML). Large pages are truncated.

    Args:
        url: Full URL (e.g. https://example.com/article)
    """
    if not url or not url.strip():
        return "Error: URL is empty."
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=_TIMEOUT,
            headers={"User-Agent": "LangGraphAgent/1.0 (personal assistant)"},
        )
        resp.raise_for_status()
        ct = (resp.headers.get("content-type") or "").lower()
        if "text/html" not in ct and "application/xhtml" not in ct:
            return f"URL returned non-HTML content (Content-Type: {ct}). Cannot extract text."
        html = resp.text
        text = _extract_text_from_html(html)
        if not text:
            return "(No extractable text found on page)"
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + f"\n\n[... truncated at {_MAX_CHARS:,} chars]"
        return f"=== Content from {url} ===\n\n{text}"
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
    except httpx.TimeoutException:
        return "Request timed out."
    except Exception as e:
        return f"Failed to fetch URL: {e}"
