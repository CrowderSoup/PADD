import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import bleach
from django.utils.safestring import mark_safe

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_video_id(url):
    """Extract the 11-char video ID from a YouTube URL, or None if it isn't one.

    Handles youtu.be short links and youtube.com watch/embed/shorts URLs. The
    strict length/charset check on the extracted ID also keeps anything else
    from reaching the iframe src we build from it in the template.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = parsed.netloc.lower()

    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            video_id = ""
            for prefix in ("/embed/", "/shorts/", "/v/"):
                if parsed.path.startswith(prefix):
                    video_id = parsed.path[len(prefix):].split("/")[0]
                    break
    else:
        return None

    return video_id if _YOUTUBE_ID_RE.match(video_id) else None

ALLOWED_TAGS = [
    "a", "abbr", "acronym", "b", "blockquote", "br", "code", "em",
    "i", "li", "ol", "p", "pre", "strong", "ul", "img", "h1", "h2",
    "h3", "h4", "h5", "h6", "figure", "figcaption", "span", "div",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "abbr": ["title"],
    "acronym": ["title"],
}


def sanitize_content(html):
    if not html:
        return mark_safe("")
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    )
    return mark_safe(cleaned)


def get_entry_type(entry):
    content = entry.get("content")
    if isinstance(content, dict):
        content_text = content.get("text", "")
    elif isinstance(content, str):
        content_text = content
    else:
        content_text = ""

    if entry.get("like-of"):
        return "like"
    if entry.get("repost-of"):
        return "repost"
    if entry.get("in-reply-to"):
        return "reply"
    if entry.get("bookmark-of"):
        return "bookmark"
    if entry.get("checkin"):
        return "checkin"
    if entry.get("video") or youtube_video_id(entry.get("url", "")):
        return "video"
    if entry.get("photo"):
        return "photo"
    name = entry.get("name", "").strip()
    if name and not content_text.strip().startswith(name):
        return "article"
    return "note"


def format_datetime(iso_str):
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt

        total = diff.total_seconds()
        if total < 0:
            return dt.strftime("%b %d, %Y")
        if total < 60:
            return "just now"
        if total < 3600:
            return f"{int(total // 60)}m ago"
        if total < 86400:
            return f"{int(total // 3600)}h ago"
        if diff.days == 1:
            return "yesterday"
        if diff.days < 7:
            return f"{diff.days}d ago"
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return iso_str
