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
                user.save()
        else:
            # Keep the most recently active user; delete the rest after
            # re-pointing all FK-like user_url fields to the canonical URL.
            users.sort(key=lambda u: u.last_login, reverse=True)
            keeper = users[0]
            duplicates = users[1:]

            # Re-point related records from duplicate URLs to canonical URL.
            dup_urls = [u.url for u in duplicates]
            for old_url in dup_urls:
                Interaction.objects.filter(user_url=old_url).update(user_url=canonical)
                DismissedBroadcast.objects.filter(user_url=old_url).update(user_url=canonical)
                Draft.objects.filter(user_url=old_url).update(user_url=canonical)
                # UserSettings has a unique constraint on user_url; merge by
                # deleting the duplicate's settings (keeper's settings win).
                UserSettings.objects.filter(user_url=old_url).delete()

            for dup in duplicates:
                dup.delete()

            if keeper.url != canonical:
                keeper.url = canonical
                keeper.save()

    # Now update user_url on remaining related models for non-duplicate variants.
    for old_url, canonical in url_map.items():
        if old_url == canonical:
            continue
        Interaction.objects.filter(user_url=old_url).update(user_url=canonical)
        DismissedBroadcast.objects.filter(user_url=old_url).update(user_url=canonical)
        Draft.objects.filter(user_url=old_url).update(user_url=canonical)
        # UserSettings: if canonical already exists (from the merge above),
        # delete the stale row; otherwise rename it.
        if UserSettings.objects.filter(user_url=canonical).exists():
            UserSettings.objects.filter(user_url=old_url).delete()
        else:
            UserSettings.objects.filter(user_url=old_url).update(user_url=canonical)


class Migration(migrations.Migration):

    dependencies = [
        ("microsub_client", "0007_draft"),
    ]

    operations = [
        migrations.RunPython(normalize_user_urls, migrations.RunPython.noop),
    ]
