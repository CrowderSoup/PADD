from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from microsub_client.models import (
    Broadcast,
    CachedEntry,
    DismissedBroadcast,
    Draft,
    Interaction,
    KnownUser,
    UserSettings,
)


normalize_user_urls = import_module(
    "microsub_client.migrations.0008_normalize_user_urls"
).normalize_user_urls


@pytest.mark.django_db
def test_normalize_user_urls_merges_conflicting_related_rows():
    canonical_url = "https://crowdersoup.com"
    old_url = "http://crowdersoup.com/"
    now = timezone.now()

    old_user = KnownUser.objects.create(url=old_url, name="Old profile")
    keeper = KnownUser.objects.create(url=canonical_url, name="Canonical profile")
    KnownUser.objects.filter(pk=old_user.pk).update(last_login=now - timedelta(days=1))
    KnownUser.objects.filter(pk=keeper.pk).update(last_login=now)

    UserSettings.objects.create(user_url=canonical_url, expand_content=True)
    UserSettings.objects.create(user_url=old_url, expand_content=False)

    first_broadcast = Broadcast.objects.create(message="Broadcast one")
    second_broadcast = Broadcast.objects.create(message="Broadcast two")
    DismissedBroadcast.objects.create(user_url=canonical_url, broadcast=first_broadcast)
    DismissedBroadcast.objects.create(user_url=old_url, broadcast=first_broadcast)
    DismissedBroadcast.objects.create(user_url=old_url, broadcast=second_broadcast)

    first_entry = CachedEntry.objects.create(url="https://post.example/1")
    second_entry = CachedEntry.objects.create(url="https://post.example/2")
    Interaction.objects.create(user_url=canonical_url, entry=first_entry, kind="like")
    Interaction.objects.create(
        user_url=old_url,
        entry=first_entry,
        kind="like",
        result_url="https://crowdersoup.com/likes/1",
    )
    Interaction.objects.create(
        user_url=old_url,
        entry=second_entry,
        kind="reply",
        content="Hello there",
        result_url="https://crowdersoup.com/replies/1",
    )

    Draft.objects.create(user_url=old_url, title="Draft title")

    normalize_user_urls(django_apps, None)

    assert KnownUser.objects.filter(url=canonical_url).count() == 1
    assert not KnownUser.objects.filter(url=old_url).exists()

    settings = UserSettings.objects.get(user_url=canonical_url)
    assert settings.expand_content is True
    assert not UserSettings.objects.filter(user_url=old_url).exists()

    assert not DismissedBroadcast.objects.filter(user_url=old_url).exists()
    assert set(
        DismissedBroadcast.objects.filter(user_url=canonical_url).values_list(
            "broadcast_id", flat=True
        )
    ) == {first_broadcast.pk, second_broadcast.pk}

    like = Interaction.objects.get(
        user_url=canonical_url,
        entry=first_entry,
        kind="like",
    )
    assert like.result_url == "https://crowdersoup.com/likes/1"

    reply = Interaction.objects.get(
        user_url=canonical_url,
        entry=second_entry,
        kind="reply",
    )
    assert reply.content == "Hello there"
    assert reply.result_url == "https://crowdersoup.com/replies/1"
    assert Interaction.objects.filter(user_url=canonical_url).count() == 2
    assert not Interaction.objects.filter(user_url=old_url).exists()

    assert Draft.objects.filter(user_url=canonical_url, title="Draft title").exists()
    assert not Draft.objects.filter(user_url=old_url).exists()
