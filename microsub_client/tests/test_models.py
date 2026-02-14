from django.db import IntegrityError
from django.test import TestCase

from microsub_client.models import Broadcast, CachedEntry, Interaction


class CachedEntryModelTests(TestCase):
    def test_str_returns_title_when_present(self):
        entry = CachedEntry(url="https://example.com/post", title="My Post")
        self.assertEqual(str(entry), "My Post")

    def test_str_returns_url_when_no_title(self):
        entry = CachedEntry(url="https://example.com/post", title="")
        self.assertEqual(str(entry), "https://example.com/post")

    def test_unique_url_constraint(self):
        CachedEntry.objects.create(url="https://example.com/1")
        with self.assertRaises(IntegrityError):
            CachedEntry.objects.create(url="https://example.com/1")


class InteractionModelTests(TestCase):
    def test_str_representation(self):
        entry = CachedEntry.objects.create(url="https://example.com/post")
        interaction = Interaction(
            user_url="https://me.example/",
            entry=entry,
            kind="like",
        )
        self.assertEqual(
            str(interaction),
            "like of https://example.com/post by https://me.example/",
        )

    def test_unique_together_constraint(self):
        entry = CachedEntry.objects.create(url="https://example.com/post")
        Interaction.objects.create(
            user_url="https://me.example/", entry=entry, kind="like",
        )
        with self.assertRaises(IntegrityError):
            Interaction.objects.create(
                user_url="https://me.example/", entry=entry, kind="like",
            )

    def test_different_kinds_allowed(self):
        entry = CachedEntry.objects.create(url="https://example.com/post")
        Interaction.objects.create(
            user_url="https://me.example/", entry=entry, kind="like",
        )
        Interaction.objects.create(
            user_url="https://me.example/", entry=entry, kind="repost",
        )
        self.assertEqual(Interaction.objects.count(), 2)


class BroadcastModelTests(TestCase):
    def test_str_truncates_long_message(self):
        msg = "A" * 100
        broadcast = Broadcast(message=msg)
        self.assertEqual(str(broadcast), "A" * 80)

    def test_str_short_message(self):
        broadcast = Broadcast(message="Hello")
        self.assertEqual(str(broadcast), "Hello")

    def test_default_is_active(self):
        b = Broadcast.objects.create(message="test")
        self.assertTrue(b.is_active)

    def test_ordering(self):
        b1 = Broadcast.objects.create(message="first")
        b2 = Broadcast.objects.create(message="second")
        results = list(Broadcast.objects.all())
        self.assertEqual(results[0], b2)
        self.assertEqual(results[1], b1)
