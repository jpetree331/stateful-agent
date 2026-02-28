"""
RSS feed tools: subscribe, manage, and fetch news/content from RSS/Atom feeds.

No Feedly or third-party account needed — reads feeds directly using feedparser.
Feed subscriptions are stored in data/rss_feeds.json and persist across restarts.

Typical RSS feed URLs:
  Hacker News:      https://news.ycombinator.com/rss
  BBC World:        https://feeds.bbci.co.uk/news/world/rss.xml
  Reuters Top News: https://feeds.reuters.com/reuters/topNews
  r/Python:         https://www.reddit.com/r/python/.rss
  Any subreddit:    https://www.reddit.com/r/<name>/.rss
  Any podcast:      usually linked on the podcast's "subscribe" page

Dependencies:
  feedparser>=6.0  (add to requirements.txt)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

# Feed subscriptions stored here — persists across restarts
_FEEDS_PATH = Path(__file__).resolve().parents[2] / "data" / "rss_feeds.json"


def _load_feeds() -> dict[str, str]:
    """Return {name: url} dict from disk."""
    if not _FEEDS_PATH.exists():
        return {}
    try:
        return json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_feeds(feeds: dict[str, str]) -> None:
    _FEEDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FEEDS_PATH.write_text(json.dumps(feeds, indent=2, ensure_ascii=False), encoding="utf-8")


def _entry_pub_dt(entry) -> datetime | None:
    """Extract published datetime from a feedparser entry (UTC-aware)."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                ts = time.mktime(val)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                continue
    return None


@tool
def rss_add_feed(name: str, url: str) -> str:
    """
    Subscribe to an RSS or Atom feed.

    Adds the feed to your permanent list (stored in data/rss_feeds.json).
    Use rss_fetch to read content from all subscribed feeds.

    Find RSS URLs by looking for the RSS/feed icon on a website, or try appending
    /rss, /feed, or /atom.xml to the site's root URL.

    Common examples:
      Hacker News:  https://news.ycombinator.com/rss
      BBC World:    https://feeds.bbci.co.uk/news/world/rss.xml
      r/Python:     https://www.reddit.com/r/python/.rss
      Any subreddit: https://www.reddit.com/r/<name>/.rss

    Args:
        name: A friendly label for this feed (e.g. "Hacker News", "BBC Tech").
        url: The RSS or Atom feed URL.
    """
    try:
        import feedparser
    except ImportError:
        return "Error: feedparser not installed. Run: pip install feedparser"

    # Quick validation — try to parse it
    parsed = feedparser.parse(url)
    if parsed.bozo and not parsed.entries:
        return f"Warning: could not parse '{url}' as RSS/Atom. Check the URL. (Error: {parsed.bozo_exception})\nAdding anyway — use rss_list_feeds to review."

    feeds = _load_feeds()
    feeds[name] = url
    _save_feeds(feeds)

    feed_title = getattr(parsed.feed, "title", None) or url
    count = len(parsed.entries)
    return f"Subscribed to '{name}': {feed_title} ({count} items currently). URL: {url}"


@tool
def rss_remove_feed(name: str) -> str:
    """
    Unsubscribe from an RSS feed by name.

    Args:
        name: The friendly name used when the feed was added.
    """
    feeds = _load_feeds()
    if name not in feeds:
        available = ", ".join(feeds) or "(none)"
        return f"Feed '{name}' not found. Available: {available}"
    url = feeds.pop(name)
    _save_feeds(feeds)
    return f"Removed feed '{name}' ({url})."


@tool
def rss_list_feeds() -> str:
    """
    List all currently subscribed RSS feeds.

    Returns each feed's friendly name and URL.
    """
    feeds = _load_feeds()
    if not feeds:
        return "No RSS feeds subscribed yet. Use rss_add_feed to add some."
    lines = [f"Subscribed RSS feeds ({len(feeds)}):"]
    for name, url in feeds.items():
        lines.append(f"  - {name}: {url}")
    return "\n".join(lines)


@tool
def rss_fetch(max_items_per_feed: int = 5, since_hours: float = 24.0) -> str:
    """
    Fetch recent items from all subscribed RSS feeds.

    Returns titles, links, and summaries of new content. Use during heartbeats
    to build a morning briefing, surface interesting news, or check for updates
    from sites the user follows. Proactively summarise and highlight what's interesting.

    Args:
        max_items_per_feed: Maximum items to return per feed (default 5).
        since_hours: Only show items published within this many hours (default 24).
                     Set to 0 to skip time filtering and always return the N newest items.
    """
    try:
        import feedparser
    except ImportError:
        return "Error: feedparser not installed. Run: pip install feedparser"

    feeds = _load_feeds()
    if not feeds:
        return "No RSS feeds subscribed. Use rss_add_feed to subscribe to feeds first."

    cutoff: datetime | None = None
    if since_hours > 0:
        cutoff = datetime.now(timezone.utc).replace(microsecond=0)
        from datetime import timedelta
        cutoff = cutoff - timedelta(hours=since_hours)

    output_sections: list[str] = []
    total_items = 0

    for feed_name, feed_url in feeds.items():
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            output_sections.append(f"=== {feed_name} ===\nError fetching: {e}\n")
            continue

        entries = parsed.entries or []

        # Filter by time if cutoff is set
        if cutoff:
            timed = []
            any_has_date = False
            for e in entries:
                pub = _entry_pub_dt(e)
                if pub is not None:
                    any_has_date = True
                    if pub >= cutoff:
                        timed.append(e)
            # If feed has no dates, fall back to newest N items
            entries = timed if any_has_date else entries

        # Trim to max_items_per_feed
        entries = entries[:max_items_per_feed]

        feed_title = getattr(parsed.feed, "title", None) or feed_name
        section = [f"=== {feed_title} ==="]

        if not entries:
            section.append("  (no new items in the last {:.0f}h)".format(since_hours))
        else:
            for entry in entries:
                title = getattr(entry, "title", "(no title)").strip()
                link = getattr(entry, "link", "").strip()
                # Summary: prefer summary, fall back to content
                summary = ""
                if hasattr(entry, "summary"):
                    summary = entry.summary.strip()
                elif hasattr(entry, "content"):
                    summary = (entry.content[0].value or "").strip()
                # Strip HTML tags roughly
                import re
                summary = re.sub(r"<[^>]+>", "", summary)[:300].strip()

                pub = _entry_pub_dt(entry)
                pub_str = pub.strftime("%b %d %H:%M UTC") if pub else ""

                section.append(f"\n• {title}")
                if pub_str:
                    section.append(f"  {pub_str}")
                if link:
                    section.append(f"  {link}")
                if summary:
                    section.append(f"  {summary}...")
                total_items += 1

        output_sections.append("\n".join(section))

    header = f"RSS Briefing — {datetime.now(timezone.utc).strftime('%A %B %d, %Y')}"
    if cutoff:
        header += f" (items from last {since_hours:.0f}h)"
    header += f"\n{total_items} item(s) across {len(feeds)} feed(s)\n"

    return header + "\n\n" + "\n\n".join(output_sections)
