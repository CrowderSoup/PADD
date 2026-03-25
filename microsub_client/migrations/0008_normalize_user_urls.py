from django.db import migrations


def _canonical(url):
    """Return the canonical form of a user URL: https://, no trailing slash."""
    if not url:
        return url
    normalized = url.strip()
    if normalized.startswith("http://"):
        normalized = "https://" + normalized[len("http://"):]
    elif "://" not in normalized:
        normalized = "https://" + normalized
    return normalized.rstrip("/")


def _merge_interactions(Interaction, old_url, canonical):
    if old_url == canonical:
        return

    for interaction in Interaction.objects.filter(user_url=old_url).order_by("pk"):
        existing = Interaction.objects.filter(
            user_url=canonical,
            entry_id=interaction.entry_id,
            kind=interaction.kind,
        ).first()
        if existing is None:
            interaction.user_url = canonical
            interaction.save(update_fields=["user_url"])
            continue

        update_fields = []
        if not existing.content and interaction.content:
            existing.content = interaction.content
            update_fields.append("content")
        if not existing.result_url and interaction.result_url:
            existing.result_url = interaction.result_url
            update_fields.append("result_url")
        if interaction.created_at and existing.created_at and interaction.created_at < existing.created_at:
            existing.created_at = interaction.created_at
            update_fields.append("created_at")
        if update_fields:
            existing.save(update_fields=update_fields)

        interaction.delete()


def _merge_dismissed_broadcasts(DismissedBroadcast, old_url, canonical):
    if old_url == canonical:
        return

    for dismissed in DismissedBroadcast.objects.filter(user_url=old_url).order_by("pk"):
        existing = DismissedBroadcast.objects.filter(
            user_url=canonical,
            broadcast_id=dismissed.broadcast_id,
        ).first()
        if existing is None:
            dismissed.user_url = canonical
            dismissed.save(update_fields=["user_url"])
            continue

        if (
            dismissed.dismissed_at
            and existing.dismissed_at
            and dismissed.dismissed_at < existing.dismissed_at
        ):
            existing.dismissed_at = dismissed.dismissed_at
            existing.save(update_fields=["dismissed_at"])

        dismissed.delete()


def _merge_user_settings(UserSettings, old_url, canonical):
    if old_url == canonical:
        return

    if UserSettings.objects.filter(user_url=canonical).exists():
        UserSettings.objects.filter(user_url=old_url).delete()
    else:
        UserSettings.objects.filter(user_url=old_url).update(user_url=canonical)


def _move_related_user_records(
    Interaction,
    UserSettings,
    DismissedBroadcast,
    Draft,
    old_url,
    canonical,
):
    _merge_interactions(Interaction, old_url, canonical)
    _merge_dismissed_broadcasts(DismissedBroadcast, old_url, canonical)
    Draft.objects.filter(user_url=old_url).update(user_url=canonical)
    _merge_user_settings(UserSettings, old_url, canonical)


def normalize_user_urls(apps, schema_editor):
    KnownUser = apps.get_model("microsub_client", "KnownUser")
    Interaction = apps.get_model("microsub_client", "Interaction")
    UserSettings = apps.get_model("microsub_client", "UserSettings")
    DismissedBroadcast = apps.get_model("microsub_client", "DismissedBroadcast")
    Draft = apps.get_model("microsub_client", "Draft")

    # Build a mapping from old URL -> canonical URL for every KnownUser.
    # We process KnownUser first because it has a unique constraint and may
    # have duplicate variants that need merging.
    url_map = {}  # old_url -> canonical_url

    for user in KnownUser.objects.all():
        canonical = _canonical(user.url)
        url_map[user.url] = canonical

    # Merge duplicate KnownUser rows that collapse to the same canonical URL.
    # Group by canonical URL; keep the row with the most recent last_login.
    from collections import defaultdict
    canonical_groups = defaultdict(list)
    for user in KnownUser.objects.all():
        canonical_groups[_canonical(user.url)].append(user)

    for canonical, users in canonical_groups.items():
        if len(users) == 1:
            user = users[0]
            if user.url != canonical:
                user.url = canonical
                user.save(update_fields=["url"])
        else:
            # Keep the most recently active user; delete the rest after
            # re-pointing all FK-like user_url fields to the canonical URL.
            users.sort(key=lambda u: u.last_login, reverse=True)
            keeper = users[0]
            duplicates = users[1:]

            # Re-point related records from duplicate URLs to canonical URL.
            dup_urls = [u.url for u in duplicates]
            for old_url in dup_urls:
                _move_related_user_records(
                    Interaction,
                    UserSettings,
                    DismissedBroadcast,
                    Draft,
                    old_url,
                    canonical,
                )

            for dup in duplicates:
                dup.delete()

            if keeper.url != canonical:
                keeper.url = canonical
                keeper.save(update_fields=["url"])

    # Now update user_url on remaining related models for non-duplicate variants.
    for old_url, canonical in url_map.items():
        if old_url == canonical:
            continue
        _move_related_user_records(
            Interaction,
            UserSettings,
            DismissedBroadcast,
            Draft,
            old_url,
            canonical,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("microsub_client", "0007_draft"),
    ]

    operations = [
        migrations.RunPython(normalize_user_urls, migrations.RunPython.noop),
    ]
