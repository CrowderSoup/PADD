from django.test import RequestFactory, TestCase, override_settings

from microsub_client.context_processors import broadcasts
from microsub_client.models import Broadcast, DismissedBroadcast


@override_settings(PADD_ADMIN_URLS=["https://admin.example/"])
class BroadcastContextProcessorTests(TestCase):
    def _make_request(self, session=None):
        request = RequestFactory().get("/")
        request.session = session or {}
        return request

    def test_unauthenticated_returns_empty(self):
        request = self._make_request()
        result = broadcasts(request)
        self.assertFalse(result["is_admin"])
        self.assertEqual(list(result["active_broadcasts"]), [])

    def test_admin_user_flagged(self):
        request = self._make_request(session={
            "access_token": "tok",
            "user_url": "https://admin.example/",
        })
        result = broadcasts(request)
        self.assertTrue(result["is_admin"])

    def test_non_admin_user_not_flagged(self):
        request = self._make_request(session={
            "access_token": "tok",
            "user_url": "https://other.example/",
        })
        result = broadcasts(request)
        self.assertFalse(result["is_admin"])

    def test_active_broadcasts_returned(self):
        Broadcast.objects.create(message="Active", is_active=True)
        Broadcast.objects.create(message="Inactive", is_active=False)
        request = self._make_request(session={
            "access_token": "tok",
            "user_url": "https://other.example/",
        })
        result = broadcasts(request)
        messages = [b.message for b in result["active_broadcasts"]]
        self.assertIn("Active", messages)
        self.assertNotIn("Inactive", messages)

    def test_dismissed_broadcasts_excluded(self):
        b = Broadcast.objects.create(message="Dismiss me", is_active=True)
        DismissedBroadcast.objects.create(
            user_url="https://other.example/", broadcast=b
        )
        request = self._make_request(session={
            "access_token": "tok",
            "user_url": "https://other.example/",
        })
        result = broadcasts(request)
        self.assertEqual(list(result["active_broadcasts"]), [])
