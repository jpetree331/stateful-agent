"""
YouTube tools: search and transcript fetching.

- youtube_search: find YouTube videos by topic using existing web search providers.
  No YouTube Data API key needed — leverages Brave or Tavily, scoped to YouTube.
- youtube_transcript: fetch captions from any public YouTube video.
  No YouTube Data API key needed — uses youtube-transcript-api.

Dependencies:
  youtube-transcript-api>=0.6  (add to requirements.txt)
"""
from __future__ import annotations

import os
import re

import httpx
from langchain_core.tools import tool

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
_TIMEOUT = 15

_MAX_CHARS = 60_000  # transcripts can be very long; truncate for context safety


def _extract_video_id(url_or_id: str) -> str:
    """Extract YouTube video ID from a URL or return bare ID as-is."""
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",        # ?v=xxxx
        r"youtu\.be/([a-zA-Z0-9_-]{11})",     # youtu.be/xxxx
        r"embed/([a-zA-Z0-9_-]{11})",          # embed/xxxx
        r"shorts/([a-zA-Z0-9_-]{11})",         # shorts/xxxx
    ]
    for pattern in patterns:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    # Assume it's a bare 11-character video ID
    cleaned = url_or_id.strip().split("?")[0].split("/")[-1]
    return cleaned


@tool
def youtube_search(query: str, max_results: int = 5) -> str:
    """
    Search YouTube for videos matching a topic or query.

    Returns a list of video titles, URLs, and video IDs. Pass any video ID to
    youtube_transcript to read its full spoken content.

    Use when the user wants to find videos on a topic, or when you want to research
    something via YouTube content autonomously.

    Args:
        query: What to search for on YouTube (e.g. "LangGraph tutorial 2024").
        max_results: How many videos to return (default 5, max 10).
    """
    max_results = min(int(max_results), 10)
    scoped_query = f"{query} site:youtube.com"

    results: list[dict] = []

    # Prefer Tavily (AI-synthesised); fall back to Brave
    if TAVILY_API_KEY:
        try:
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": scoped_query,
                    "search_depth": "basic",
                    "include_answer": False,
                    "max_results": max_results,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            raw = resp.json().get("results", [])
            results = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in raw]
        except Exception as e:
            return f"YouTube search failed (Tavily): {e}"
    elif BRAVE_API_KEY:
        try:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": scoped_query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": BRAVE_API_KEY,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            raw = resp.json().get("web", {}).get("results", [])
            results = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in raw]
        except Exception as e:
            return f"YouTube search failed (Brave): {e}"
    else:
        return "Error: configure TAVILY_API_KEY or BRAVE_API_KEY in .env to enable YouTube search."

    # Filter to YouTube URLs and extract video IDs
    yt_results = []
    for r in results:
        url = r.get("url", "")
        if "youtube.com/watch" in url or "youtu.be/" in url:
            video_id = _extract_video_id(url)
            yt_results.append({"title": r["title"], "url": url, "video_id": video_id})

    if not yt_results:
        return f"No YouTube videos found for '{query}'. Try rephrasing or use web_search directly."

    lines = [f"=== YouTube Search: {query} ===\n"]
    for i, r in enumerate(yt_results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   URL: {r['url']}")
        lines.append(f"   ID:  {r['video_id']}  ← pass to youtube_transcript\n")

    return "\n".join(lines)


@tool
def youtube_transcript(url_or_id: str, language: str = "en") -> str:
    """
    Fetch the transcript (captions) of a YouTube video.

    Works on any public YouTube video that has captions (auto-generated or manual).
    Returns the full spoken text with timestamps, ready to summarise or analyse.

    Use when the user shares a YouTube link and wants a summary, when you want to learn
    from a video without watching it, or for research from video content.

    Args:
        url_or_id: YouTube video URL (any format) or bare video ID (11 characters).
                   Examples: "https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ",
                             "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        language: Preferred caption language code (default "en" for English).
                  Falls back to auto-generated captions if manual ones aren't available.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    except ImportError:
        return "Error: youtube-transcript-api not installed. Run: pip install youtube-transcript-api"

    video_id = _extract_video_id(url_or_id)
    url_display = f"https://youtube.com/watch?v={video_id}"

    try:
        # v1.x API: instantiate the class, use .list() instead of .list_transcripts()
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        try:
            transcript = transcript_list.find_transcript([language])
        except NoTranscriptFound:
            # Fall back to auto-generated in any language
            try:
                transcript = transcript_list.find_generated_transcript([language])
            except NoTranscriptFound:
                # Take whatever's available
                transcript = next(iter(transcript_list))

        entries = transcript.fetch()
        lang_used = transcript.language_code

        # Format: group into readable paragraphs by timestamp
        # v1.x entries are FetchedTranscriptSnippet objects (not dicts)
        lines = [f"=== YouTube Transcript ===", f"Video: {url_display}", f"Language: {lang_used}\n"]
        full_text = ""
        for entry in entries:
            t = int(entry.start)
            mins, secs = divmod(t, 60)
            hrs, mins = divmod(mins, 60)
            ts = f"[{hrs:02d}:{mins:02d}:{secs:02d}]" if hrs else f"[{mins:02d}:{secs:02d}]"
            text = entry.text.replace("\n", " ").strip()
            full_text += f"{ts} {text}\n"

        truncated = ""
        if len(full_text) > _MAX_CHARS:
            full_text = full_text[:_MAX_CHARS]
            truncated = f"\n[... transcript truncated at {_MAX_CHARS:,} chars]"

        lines.append(full_text + truncated)
        return "\n".join(lines)

    except TranscriptsDisabled:
        return f"Error: captions are disabled for this video ({url_display})."
    except Exception as e:
        return f"Error fetching transcript for '{video_id}': {e}"
