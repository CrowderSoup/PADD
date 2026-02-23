from datetime import datetime, timezone

import bleach
from django.utils.safestring import mark_safe

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
    if entry.get("photo"):
        return "photo"
    if entry.get("name") and entry.get("name") != content_text[:100]:
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

        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                minutes = diff.seconds // 60
                if minutes == 0:
                    return "just now"
                return f"{minutes}m ago"
            return f"{hours}h ago"
        if diff.days == 1:
            return "yesterday"
        if diff.days < 7:
            return f"{diff.days}d ago"
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return iso_str
