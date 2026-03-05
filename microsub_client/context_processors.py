import hashlib

from django.conf import settings
from django.core.cache import cache

from .models import Broadcast, DismissedBroadcast

BROADCASTS_CACHE_TTL = 30  # seconds


def _broadcasts_cache_key(user_url: str) -> str:
    return f"broadcasts:{hashlib.md5(user_url.encode()).hexdigest()}"


def broadcasts(request):
    user_url = request.session.get("user_url", "")
    is_admin = user_url in settings.PADD_ADMIN_URLS

    if not request.session.get("access_token"):
        return {"is_admin": False, "active_broadcasts": []}

    key = _broadcasts_cache_key(user_url)
    cached = cache.get(key)
    if cached is not None:
        return {"is_admin": is_admin, "active_broadcasts": cached}

    dismissed_ids = DismissedBroadcast.objects.filter(
        user_url=user_url
    ).values_list("broadcast_id", flat=True)
    active_broadcasts = list(
        Broadcast.objects.filter(is_active=True).exclude(id__in=dismissed_ids)
    )

    cache.set(key, active_broadcasts, BROADCASTS_CACHE_TTL)
    return {
        "is_admin": is_admin,
        "active_broadcasts": active_broadcasts,
    }
