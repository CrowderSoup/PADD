from django.conf import settings

from .models import Broadcast, DismissedBroadcast


def broadcasts(request):
    user_url = request.session.get("user_url", "")
    is_admin = user_url in settings.PADD_ADMIN_URLS

    if not request.session.get("access_token"):
        return {"is_admin": False, "active_broadcasts": []}

    dismissed_ids = DismissedBroadcast.objects.filter(
        user_url=user_url
    ).values_list("broadcast_id", flat=True)
    active_broadcasts = Broadcast.objects.filter(is_active=True).exclude(
        id__in=dismissed_ids
    )

    return {
        "is_admin": is_admin,
        "active_broadcasts": active_broadcasts,
    }
