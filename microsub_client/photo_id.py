"""Deterministic short id derived from a photo's URL.

Used to build stable, deep-linkable photo-edit URLs (see the "dedicated
edit route" feature of the photo editor redesign) without a database
Upload/Photo model — ``Draft.photos`` is a plain list of URL strings, so
the id is computed from the URL itself rather than stored anywhere.

The same FNV-1a implementation exists in ``static/js/new-post.js`` so the
client can compute the same id right after upload — before any page
reload — to build a thumbnail's edit link. Keep the two in sync.

FNV-1a assumes the input is US-ASCII, true for any well-formed absolute
URL per RFC 3986 (unreserved/reserved characters and %XX escapes are all
ASCII).
"""

_FNV_OFFSET_BASIS = 0x811C9DC5
_FNV_PRIME = 0x01000193
_MASK32 = 0xFFFFFFFF


def photo_url_hash(url: str) -> str:
    h = _FNV_OFFSET_BASIS
    for ch in url:
        h ^= ord(ch) & 0xFF
        h = (h * _FNV_PRIME) & _MASK32
    return format(h, "08x")
