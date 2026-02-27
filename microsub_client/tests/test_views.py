import logging
from unittest.mock import patch

from defusedxml.common import DefusedXmlException
from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile
from django.test import TestCase, override_settings

_quiet_request = logging.getLogger("django.request")
_quiet_request.setLevel(logging.CRITICAL)

from microsub_client import api, micropub
from microsub_client.models import (
    Broadcast,
    CachedEntry,
    DismissedBroadcast,
    Draft,
    Interaction,
    KnownUser,
    UserSettings,
)

from .conftest import SIMPLE_STORAGES, auth_session


@override_settings(STORAGES=SIMPLE_STORAGES)
class ClientIdMetadataViewTests(TestCase):
    def test_returns_json_with_expected_fields(self):
        response = self.client.get("/id")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        body = response.json()
        self.assertEqual(body["client_id"], "http://testserver/id")
        self.assertEqual(body["client_name"], "PADD")
        self.assertEqual(body["client_uri"], "http://testserver/")
        self.assertTrue(body["logo_uri"].startswith("http://testserver/static/logo"))
        self.assertEqual(body["redirect_uris"], ["http://testserver/login/callback/"])
        self.assertEqual(body["scope"], "read follow channels create")


@override_settings(STORAGES=SIMPLE_STORAGES)
class LoginViewTests(TestCase):
    def test_get_renders_login_page(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)

    def test_post_empty_url_shows_error(self):
        response = self.client.post("/login/", {"url": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter your domain")

    def test_already_authenticated_redirects(self):
        session = self.client.session
        session["access_token"] = "tok"
        session.save()
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/app/")

    @patch("microsub_client.views.generate_pkce_pair", return_value=("verifier", "challenge"))
    @patch("microsub_client.views.discover_endpoints", return_value={
        "authorization_endpoint": "https://auth.example/authorize",
        "token_endpoint": "https://auth.example/token",
        "microsub": "https://user.example/microsub",
        "micropub": "https://user.example/micropub",
    })
    @patch("microsub_client.views.build_authorization_url", return_value="https://auth.example/next")
    def test_successful_login_redirects_to_auth(self, mock_build, _mock_disc, _mock_pkce):
        response = self.client.post("/login/", {"url": "https://user.example/"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://auth.example/next")
        self.assertEqual(mock_build.call_args.kwargs["client_id"], "http://testserver/id")

    @patch("microsub_client.views.discover_endpoints", return_value={
        "authorization_endpoint": None,
        "token_endpoint": "https://auth.example/token",
        "microsub": "https://user.example/microsub",
        "micropub": None,
    })
    def test_missing_auth_endpoint_shows_error(self, _mock):
        response = self.client.post("/login/", {"url": "https://user.example/"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "authorization endpoint")

    @patch("microsub_client.views.discover_endpoints", return_value={
        "authorization_endpoint": "https://auth.example/auth",
        "token_endpoint": None,
        "microsub": "https://user.example/microsub",
        "micropub": None,
    })
    def test_missing_token_endpoint_shows_error(self, _mock):
        response = self.client.post("/login/", {"url": "https://user.example/"})
        self.assertContains(response, "token endpoint")

    @patch("microsub_client.views.discover_endpoints", return_value={
        "authorization_endpoint": "https://auth.example/auth",
        "token_endpoint": "https://auth.example/token",
        "microsub": None,
        "micropub": None,
    })
    def test_missing_microsub_endpoint_shows_error(self, _mock):
        response = self.client.post("/login/", {"url": "https://user.example/"})
        self.assertContains(response, "Microsub endpoint")


@override_settings(STORAGES=SIMPLE_STORAGES)
class CallbackViewTests(TestCase):
    def test_missing_code_redirects_to_login(self):
        response = self.client.get("/login/callback/", {"state": "abc"})
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    def test_missing_state_redirects_to_login(self):
        response = self.client.get("/login/callback/", {"code": "abc"})
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    def test_state_mismatch_redirects_to_login(self):
        session = self.client.session
        session["auth_state"] = "expected"
        session.save()
        response = self.client.get("/login/callback/", {"code": "abc", "state": "wrong"})
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    @patch("microsub_client.views.fetch_hcard", return_value={"name": "Jane", "photo": None})
    @patch("microsub_client.views.exchange_code_for_token", return_value={
        "access_token": "tok123", "me": "https://me.example/",
    })
    def test_successful_callback_sets_session(self, _mock_exchange, _mock_hcard):
        session = self.client.session
        session["auth_state"] = "test-state"
        session["token_endpoint"] = "https://auth.example/token"
        session["code_verifier"] = "verifier"
        session["user_url"] = "https://me.example/"
        session["microsub_endpoint"] = "https://microsub.example/"
        session.save()
        response = self.client.get("/login/callback/", {"code": "abc", "state": "test-state"})
        self.assertRedirects(response, "/app/", fetch_redirect_response=False)
        session = self.client.session
        self.assertEqual(session["access_token"], "tok123")
        self.assertEqual(session["user_name"], "Jane")
        self.assertNotIn("auth_state", session)
        self.assertNotIn("code_verifier", session)

    @patch("microsub_client.views.fetch_hcard", return_value={"name": "Jane", "photo": "https://me.example/photo.jpg"})
    @patch("microsub_client.views.exchange_code_for_token", return_value={
        "access_token": "tok123", "me": "https://me.example/",
    })
    def test_callback_creates_known_user(self, _mock_exchange, _mock_hcard):
        session = self.client.session
        session["auth_state"] = "test-state"
        session["token_endpoint"] = "https://auth.example/token"
        session["code_verifier"] = "verifier"
        session["user_url"] = "https://me.example/"
        session["microsub_endpoint"] = "https://microsub.example/"
        session.save()
        self.client.get("/login/callback/", {"code": "abc", "state": "test-state"})
        user = KnownUser.objects.get(url="https://me.example/")
        self.assertEqual(user.name, "Jane")
        self.assertEqual(user.photo, "https://me.example/photo.jpg")

    @patch("microsub_client.views.fetch_hcard", return_value={"name": "Jane Updated", "photo": ""})
    @patch("microsub_client.views.exchange_code_for_token", return_value={
        "access_token": "tok123", "me": "https://me.example/",
    })
    def test_callback_updates_existing_known_user(self, _mock_exchange, _mock_hcard):
        KnownUser.objects.create(url="https://me.example/", name="Jane", photo="https://me.example/old.jpg")
        session = self.client.session
        session["auth_state"] = "test-state"
        session["token_endpoint"] = "https://auth.example/token"
        session["code_verifier"] = "verifier"
        session["user_url"] = "https://me.example/"
        session["microsub_endpoint"] = "https://microsub.example/"
        session.save()
        self.client.get("/login/callback/", {"code": "abc", "state": "test-state"})
        user = KnownUser.objects.get(url="https://me.example/")
        self.assertEqual(user.name, "Jane Updated")
        self.assertEqual(KnownUser.objects.count(), 1)


@override_settings(STORAGES=SIMPLE_STORAGES)
class LogoutViewTests(TestCase):
    def test_logout_flushes_session_and_redirects(self):
        session = self.client.session
        session["access_token"] = "tok"
        session.save()
        response = self.client.get("/logout/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)


@override_settings(STORAGES=SIMPLE_STORAGES)
class MarkReadViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/mark-read/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.mark_read")
    def test_missing_params_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/mark-read/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.mark_read")
    def test_success_returns_200(self, mock_mark):
        mock_mark.return_value = {}
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/mark-read/", {"channel": "ch1", "entry": "e1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Read", response.content.decode())

    @patch("microsub_client.views.api.mark_read", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/mark-read/", {"channel": "ch1", "entry": "e1"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class MicropubLikeViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/micropub/like/")
        self.assertEqual(response.status_code, 405)

    def test_no_micropub_endpoint_returns_400(self):
        s = auth_session()
        del s["micropub_endpoint"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.post("/api/micropub/like/", {"entry_url": "https://example.com"})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.micropub.like", return_value="https://me.example/like/1")
    def test_successful_like_creates_interaction(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/like/", {"entry_url": "https://example.com/post"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Interaction.objects.filter(
                user_url="https://me.example/",
                kind="like",
                entry__url="https://example.com/post",
            ).exists()
        )

    @patch("microsub_client.views.micropub.like", return_value="https://me.example/like/1")
    def test_duplicate_like_is_idempotent(self, mock_like):
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post("/api/micropub/like/", {"entry_url": "https://example.com/post"})
        # Second like should not call micropub again
        mock_like.reset_mock()
        self.client.post("/api/micropub/like/", {"entry_url": "https://example.com/post"})
        mock_like.assert_not_called()
        self.assertEqual(
            Interaction.objects.filter(kind="like", entry__url="https://example.com/post").count(),
            1,
        )


@override_settings(STORAGES=SIMPLE_STORAGES)
class MicropubReplyViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/micropub/reply/")
        self.assertEqual(response.status_code, 405)

    def test_missing_entry_url_returns_400(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/reply/", {"content": "Hello"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"Entry URL is required")

    def test_missing_content_returns_400(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/reply/", {"entry_url": "https://example.com"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"Content is required")

    def test_whitespace_only_content_returns_400(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/reply/", {
            "entry_url": "https://example.com",
            "content": "   ",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"Content is required")

    def test_missing_micropub_endpoint_returns_400(self):
        session = self.client.session
        session.update({
            "access_token": "tok",
            "user_url": "https://me.example/",
        })
        session.save()
        response = self.client.post("/api/micropub/reply/", {
            "entry_url": "https://example.com",
            "content": "Hello",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"Micropub not available")

    @patch("microsub_client.views.micropub.reply", side_effect=micropub.MicropubError("upstream fail"))
    def test_micropub_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/reply/", {
            "entry_url": "https://example.com/post",
            "content": "Nice post!",
        })
        self.assertEqual(response.status_code, 502)
        self.assertIn(b"upstream fail", response.content)

    @patch("microsub_client.views.micropub.reply", return_value="https://me.example/reply/1")
    def test_successful_reply(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/reply/", {
            "entry_url": "https://example.com/post",
            "content": "Nice post!",
        })
        self.assertEqual(response.status_code, 200)
        interaction = Interaction.objects.get(kind="reply")
        self.assertEqual(interaction.content, "Nice post!")

    @patch("microsub_client.views.micropub.reply", return_value="https://me.example/reply/2")
    def test_reply_overwrites_existing_interaction(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post("/api/micropub/reply/", {
            "entry_url": "https://example.com/post",
            "content": "First reply",
        })
        _mock.return_value = "https://me.example/reply/3"
        self.client.post("/api/micropub/reply/", {
            "entry_url": "https://example.com/post",
            "content": "Updated reply",
        })
        self.assertEqual(Interaction.objects.filter(kind="reply").count(), 1)
        interaction = Interaction.objects.get(kind="reply")
        self.assertEqual(interaction.content, "Updated reply")
        self.assertEqual(interaction.result_url, "https://me.example/reply/3")


@override_settings(PADD_ADMIN_URLS=["https://admin.example/"], STORAGES=SIMPLE_STORAGES)
class BroadcastViewTests(TestCase):
    def _admin_session(self):
        s = auth_session()
        s["user_url"] = "https://admin.example/"
        return s

    def test_admin_view_requires_admin(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 403)

    def test_admin_view_accessible_by_admin(self):
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_create_requires_admin(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/admin/broadcasts/create/", {"message": "test"})
        self.assertEqual(response.status_code, 403)

    def test_create_broadcast(self):
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        self.client.post("/admin/broadcasts/create/", {"message": "Hello world"})
        self.assertTrue(Broadcast.objects.filter(message="Hello world").exists())

    def test_toggle_broadcast(self):
        b = Broadcast.objects.create(message="Toggle me", is_active=True)
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        self.client.post(f"/admin/broadcasts/{b.id}/toggle/")
        b.refresh_from_db()
        self.assertFalse(b.is_active)

    def test_toggle_nonexistent_returns_404(self):
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.post("/admin/broadcasts/99999/toggle/")
        self.assertEqual(response.status_code, 404)

    def test_dismiss_broadcast(self):
        b = Broadcast.objects.create(message="Dismiss me")
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post(f"/api/broadcast/{b.id}/dismiss/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            DismissedBroadcast.objects.filter(
                user_url="https://me.example/", broadcast=b
            ).exists()
        )

    def test_dismiss_broadcast_idempotent(self):
        b = Broadcast.objects.create(message="Dismiss me twice")
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post(f"/api/broadcast/{b.id}/dismiss/")
        self.client.post(f"/api/broadcast/{b.id}/dismiss/")
        self.assertEqual(
            DismissedBroadcast.objects.filter(
                user_url="https://me.example/", broadcast=b
            ).count(),
            1,
        )

    def test_dismiss_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/broadcast/1/dismiss/")
        self.assertEqual(response.status_code, 405)


@override_settings(PADD_ADMIN_URLS=["https://admin.example/"], STORAGES=SIMPLE_STORAGES)
class AdminUserListTests(TestCase):
    def _admin_session(self):
        s = auth_session()
        s["user_url"] = "https://admin.example/"
        return s

    def test_admin_view_shows_users(self):
        KnownUser.objects.create(url="https://alice.example/", name="Alice")
        KnownUser.objects.create(url="https://bob.example/", name="Bob")
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")

    def test_search_filters_users(self):
        KnownUser.objects.create(url="https://alice.example/", name="Alice")
        KnownUser.objects.create(url="https://bob.example/", name="Bob")
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.get("/admin/?q=alice")
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bob")

    def test_search_by_url(self):
        KnownUser.objects.create(url="https://alice.example/", name="Alice")
        KnownUser.objects.create(url="https://bob.example/", name="Bob")
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.get("/admin/?q=bob.example")
        self.assertNotContains(response, "Alice")
        self.assertContains(response, "Bob")

    def test_pagination(self):
        for i in range(30):
            KnownUser.objects.create(url=f"https://user{i}.example/", name=f"User {i}")
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.get("/admin/")
        self.assertContains(response, "Page 1 of 2")
        response = self.client.get("/admin/?page=2")
        self.assertContains(response, "Page 2 of 2")

    def test_non_admin_gets_403(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 403)


@override_settings(STORAGES=SIMPLE_STORAGES)
class MarkUnreadViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/mark-unread/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.mark_unread")
    def test_missing_params_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/mark-unread/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_channels", return_value=[])
    @patch("microsub_client.views.api.mark_unread")
    def test_success_returns_200(self, mock_mark, _mock_ch):
        mock_mark.return_value = {}
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/mark-unread/", {"channel": "ch1", "entry": "e1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mark Read", response.content.decode())

    @patch("microsub_client.views.api.mark_unread", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/mark-unread/", {"channel": "ch1", "entry": "e1"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class RemoveEntryViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/timeline/remove/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.remove_entry")
    def test_missing_params_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/timeline/remove/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.remove_entry")
    def test_success_returns_empty_200(self, mock_remove):
        mock_remove.return_value = {}
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/timeline/remove/", {"channel": "ch1", "entry": "e1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    @patch("microsub_client.views.api.remove_entry", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/timeline/remove/", {"channel": "ch1", "entry": "e1"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class ChannelCreateViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/channels/create/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.create_channel")
    def test_empty_name_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/create/", {"name": ""})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "new", "name": "New"}])
    @patch("microsub_client.views.api.create_channel", return_value={"uid": "new", "name": "New"})
    def test_success_returns_channel_list(self, _mock_create, _mock_ch):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/create/", {"name": "New"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("New", response.content.decode())

    @patch("microsub_client.views.api.create_channel", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/create/", {"name": "New"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class ChannelMarkReadViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/channels/mark-read/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.mark_channel_read")
    def test_missing_channel_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/mark-read/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "ch1", "name": "One"}])
    @patch("microsub_client.views.api.mark_channel_read", return_value={})
    def test_success_returns_channel_list(self, mock_mark, _mock_ch):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/mark-read/", {"channel": "ch1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mark as read", response.content.decode())
        mock_mark.assert_called_once_with("https://microsub.example/", "test-token", "ch1")

    @patch("microsub_client.views.api.mark_channel_read", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/mark-read/", {"channel": "ch1"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class ChannelRenameViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/channels/rename/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.update_channel")
    def test_missing_params_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/rename/", {"channel": "ch1"})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "ch1", "name": "Renamed"}])
    @patch("microsub_client.views.api.update_channel", return_value={})
    def test_success_returns_channel_list(self, _mock_update, _mock_ch):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/rename/", {"channel": "ch1", "name": "Renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Renamed", response.content.decode())


@override_settings(STORAGES=SIMPLE_STORAGES)
class ChannelDeleteViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/channels/delete/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.delete_channel")
    def test_missing_channel_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/delete/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_channels", return_value=[])
    @patch("microsub_client.views.api.delete_channel", return_value={})
    def test_success_returns_channel_list(self, _mock_del, _mock_ch):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/delete/", {"channel": "ch1"})
        self.assertEqual(response.status_code, 200)

    @patch("microsub_client.views.api.delete_channel", side_effect=api.MicrosubError("Cannot delete"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/delete/", {"channel": "notifications"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class ChannelOrderViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/channels/order/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.order_channels")
    def test_missing_channels_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/order/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "ch2", "name": "Two"}, {"uid": "ch1", "name": "One"},
    ])
    @patch("microsub_client.views.api.order_channels", return_value={})
    def test_success_returns_channel_list(self, _mock_order, _mock_ch):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/channels/order/", {"channels[]": ["ch2", "ch1"]})
        self.assertEqual(response.status_code, 200)


@override_settings(STORAGES=SIMPLE_STORAGES)
class FeedSearchViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/search/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.search_feeds")
    def test_empty_query_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/search/", {"query": ""})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.search_feeds", return_value={"results": [{"url": "https://feed.example/", "type": "feed"}]})
    def test_success_returns_results(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/search/", {"query": "example.com", "channel": "ch1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("feed.example", response.content.decode())

    @patch("microsub_client.views.api.search_feeds", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/search/", {"query": "test"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class FeedPreviewViewTests(TestCase):
    @patch("microsub_client.views.api.preview_feed")
    def test_missing_url_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/preview/")
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.preview_feed", return_value={"items": [{"name": "Post 1"}]})
    def test_success_returns_preview(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/preview/?url=https://feed.example/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Post 1", response.content.decode())

    @patch("microsub_client.views.api.preview_feed", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/preview/?url=https://feed.example/")
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class FeedListViewTests(TestCase):
    @patch("microsub_client.views.api.get_follows", return_value={"items": [{"url": "https://feed.example/"}]})
    def test_success_returns_feed_list(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/list/ch1/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("feed.example", response.content.decode())

    @patch("microsub_client.views.api.get_follows", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/list/ch1/")
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class FeedFollowViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/follow/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.follow_feed")
    def test_missing_params_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/follow/", {"channel": "ch1"})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_follows", return_value={"items": [{"url": "https://feed.example/"}]})
    @patch("microsub_client.views.api.follow_feed", return_value={})
    def test_success_returns_feed_list(self, _mock_follow, _mock_follows):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/follow/", {"channel": "ch1", "url": "https://feed.example/"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("feed.example", response.content.decode())

    @patch("microsub_client.views.api.follow_feed", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/follow/", {"channel": "ch1", "url": "https://feed.example/"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class FeedUnfollowViewTests(TestCase):
    def test_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/feeds/unfollow/")
        self.assertEqual(response.status_code, 405)

    @patch("microsub_client.views.api.unfollow_feed")
    def test_missing_params_returns_400(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/unfollow/", {"channel": "ch1"})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.get_follows", return_value={"items": []})
    @patch("microsub_client.views.api.unfollow_feed", return_value={})
    def test_success_returns_updated_feed_list(self, _mock_unfollow, _mock_follows):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/unfollow/", {"channel": "ch1", "url": "https://feed.example/"})
        self.assertEqual(response.status_code, 200)

    @patch("microsub_client.views.api.unfollow_feed", side_effect=api.MicrosubError("fail"))
    def test_api_error_returns_502(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/feeds/unfollow/", {"channel": "ch1", "url": "https://feed.example/"})
        self.assertEqual(response.status_code, 502)


@override_settings(STORAGES=SIMPLE_STORAGES)
class IndexViewTests(TestCase):
    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "home", "name": "Home"},
    ])
    def test_redirects_to_first_channel(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/app/")
        self.assertRedirects(response, "/channel/home/", fetch_redirect_response=False)

    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "default", "name": "Default"},
    ])
    def test_single_channel_redirects(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/app/")
        self.assertRedirects(response, "/channel/default/", fetch_redirect_response=False)

    @patch("microsub_client.views.api.get_channels", side_effect=api.MicrosubError("fail"))
    def test_api_error_redirects_to_login(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/app/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)


@override_settings(STORAGES=SIMPLE_STORAGES)
class LandingViewTests(TestCase):
    def test_landing_renders_for_anonymous_users(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Captain's Log")
        self.assertContains(response, "PADD is your console for the IndieWeb")

    def test_landing_redirects_authenticated_users(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/")
        self.assertRedirects(response, "/app/", fetch_redirect_response=False)


@override_settings(STORAGES=SIMPLE_STORAGES)
class TimelineViewTests(TestCase):
    @patch("microsub_client.views.api.get_timeline", return_value={"items": [], "paging": {}})
    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "home", "name": "Home"},
    ])
    def test_renders_timeline(self, _mock_ch, _mock_tl):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/channel/home/")
        self.assertEqual(response.status_code, 200)

    @patch("microsub_client.views.api.get_channels", side_effect=api.MicrosubError("fail"))
    def test_api_error_redirects_to_login(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/channel/home/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    @patch("microsub_client.views.api.get_timeline", return_value={"items": [], "paging": {}})
    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "home", "name": "Home"},
    ])
    def test_context_contains_mark_read_behavior_default(self, _mock_ch, _mock_tl):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/channel/home/")
        self.assertEqual(response.context["mark_read_behavior"], "explicit")

    @patch("microsub_client.views.api.get_timeline", return_value={"items": [], "paging": {}})
    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "home", "name": "Home"},
    ])
    def test_context_contains_mark_read_behavior_custom(self, _mock_ch, _mock_tl):
        UserSettings.objects.create(
            user_url="https://me.example/", mark_read_behavior="scroll_past"
        )
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/channel/home/")
        self.assertEqual(response.context["mark_read_behavior"], "scroll_past")

    @patch("microsub_client.views.api.get_timeline", return_value={
        "items": [{"_id": "47444000", "name": "Turtle wall", "photo": ["https://example.com/photo.jpg"]}],
        "paging": {},
    })
    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "home", "name": "Home"},
    ])
    def test_htmx_channel_switch_handles_entry_missing_url(self, _mock_ch, _mock_tl):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/channel/home/", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Turtle wall")

    def test_missing_user_url_redirects_and_does_not_create_anonymous_settings(self):
        s = auth_session()
        del s["user_url"]
        session = self.client.session
        session.update(s)
        session.save()

        response = self.client.get("/channel/home/")

        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.assertFalse(UserSettings.objects.filter(user_url="").exists())


@override_settings(STORAGES=SIMPLE_STORAGES)
class SettingsViewTests(TestCase):
    @patch("microsub_client.views.api.get_channels", return_value=[])
    def test_renders_settings(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/settings/")
        self.assertEqual(response.status_code, 200)

    @patch("microsub_client.views.api.get_channels", return_value=[])
    def test_post_saves_default_filter(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post("/settings/", {"default_filter": "unread"})
        us = UserSettings.objects.get(user_url="https://me.example/")
        self.assertEqual(us.default_filter, "unread")

    @patch("microsub_client.views.api.get_channels", return_value=[])
    def test_post_saves_mark_read_behavior(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post("/settings/", {
            "default_filter": "all",
            "mark_read_behavior": "scroll_past",
        })
        us = UserSettings.objects.get(user_url="https://me.example/")
        self.assertEqual(us.mark_read_behavior, "scroll_past")

    @patch("microsub_client.views.api.get_channels", return_value=[])
    def test_post_saves_expand_content(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post("/settings/", {
            "default_filter": "all",
            "expand_content": "on",
        })
        us = UserSettings.objects.get(user_url="https://me.example/")
        self.assertTrue(us.expand_content)

    @patch("microsub_client.views.api.get_channels", return_value=[])
    def test_post_expand_content_off_when_unchecked(self, _mock):
        UserSettings.objects.create(
            user_url="https://me.example/", expand_content=True
        )
        session = self.client.session
        session.update(auth_session())
        session.save()
        self.client.post("/settings/", {"default_filter": "all"})
        us = UserSettings.objects.get(user_url="https://me.example/")
        self.assertFalse(us.expand_content)

    def test_missing_user_url_redirects_and_does_not_create_anonymous_settings(self):
        s = auth_session()
        del s["user_url"]
        session = self.client.session
        session.update(s)
        session.save()

        response = self.client.get("/settings/")

        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.assertFalse(UserSettings.objects.filter(user_url="").exists())


_CONFIG_WITH_MEDIA = {
    "media-endpoint": "https://media.example/",
    "syndicate-to": [{"uid": "https://twitter.com/", "name": "Twitter"}],
}
_CONFIG_EMPTY = {"syndicate-to": []}


@override_settings(STORAGES=SIMPLE_STORAGES)
class NewPostViewTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    # --- GET ---

    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_WITH_MEDIA)
    def test_get_renders_form(self, _mock):
        self._auth_session()
        response = self.client.get("/new/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "new_post.html")
        self.assertContains(response, "<form")

    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_WITH_MEDIA)
    def test_get_exposes_media_endpoint_flag(self, _mock):
        self._auth_session()
        response = self.client.get("/new/")
        self.assertTrue(response.context["has_media_endpoint"])

    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_WITH_MEDIA)
    def test_get_exposes_syndication_targets(self, _mock):
        self._auth_session()
        response = self.client.get("/new/")
        targets = response.context["syndicate_to"]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["uid"], "https://twitter.com/")

    def test_get_no_micropub_endpoint_returns_400(self):
        s = auth_session()
        del s["micropub_endpoint"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.get("/new/")
        self.assertEqual(response.status_code, 400)

    def test_get_no_access_token_redirects_to_login(self):
        # The auth middleware handles this before the view runs.
        s = auth_session()
        del s["access_token"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.get("/new/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    @patch("microsub_client.views.micropub.query_config", side_effect=micropub.MicropubError("fail"))
    def test_get_config_failure_renders_form_without_extras(self, _mock):
        self._auth_session()
        response = self.client.get("/new/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["has_media_endpoint"])
        self.assertEqual(response.context["syndicate_to"], [])

    # --- POST ---

    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_empty_content_returns_error(self, _mock):
        self._auth_session()
        response = self.client.post("/new/", {"content": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Content is required")

    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_whitespace_content_returns_error(self, _mock):
        self._auth_session()
        response = self.client.post("/new/", {"content": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Content is required")

    @patch("microsub_client.views.micropub.create_post", return_value="https://me.example/post/1")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_success_renders_success_with_url(self, _mock_config, _mock_create):
        self._auth_session()
        response = self.client.post("/new/", {"content": "Hello world"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["success"])
        self.assertEqual(response.context["result_url"], "https://me.example/post/1")

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_success_no_location_renders_success(self, _mock_config, _mock_create):
        self._auth_session()
        response = self.client.post("/new/", {"content": "Hello world"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["success"])
        self.assertEqual(response.context["result_url"], "")

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_with_name_passes_name(self, _mock_config, mock_create):
        self._auth_session()
        self.client.post("/new/", {"content": "Body", "name": "My Article"})
        self.assertEqual(mock_create.call_args.kwargs["name"], "My Article")

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_with_tags_passes_category_list(self, _mock_config, mock_create):
        self._auth_session()
        self.client.post("/new/", {"content": "Tagged", "tags": "python,web,django"})
        self.assertEqual(sorted(mock_create.call_args.kwargs["category"]), ["django", "python", "web"])

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_without_tags_passes_none_category(self, _mock_config, mock_create):
        self._auth_session()
        self.client.post("/new/", {"content": "No tags"})
        self.assertIsNone(mock_create.call_args.kwargs["category"])

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_with_photos_passes_photo_list(self, _mock_config, mock_create):
        self._auth_session()
        self.client.post("/new/", {
            "content": "Photo post",
            "photo": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        })
        self.assertEqual(
            mock_create.call_args.kwargs["photo"],
            ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        )

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_with_location_passes_location(self, _mock_config, mock_create):
        self._auth_session()
        self.client.post("/new/", {"content": "Here I am", "location": "geo:37.123,-122.456"})
        self.assertEqual(mock_create.call_args.kwargs["location"], "geo:37.123,-122.456")

    @patch("microsub_client.views.micropub.create_post", return_value="")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_with_syndicate_to_passes_list(self, _mock_config, mock_create):
        self._auth_session()
        self.client.post("/new/", {
            "content": "Syndicated",
            "syndicate_to": ["https://twitter.com/", "https://mastodon.social/"],
        })
        syndicate_to = mock_create.call_args.kwargs["syndicate_to"]
        self.assertIn("https://twitter.com/", syndicate_to)
        self.assertIn("https://mastodon.social/", syndicate_to)

    @patch("microsub_client.views.micropub.create_post", side_effect=micropub.MicropubError("upstream fail"))
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_EMPTY)
    def test_post_micropub_error_shows_error(self, _mock_config, _mock_create):
        self._auth_session()
        response = self.client.post("/new/", {"content": "Hello"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "upstream fail")
        self.assertFalse(response.context.get("success", False))

    def test_post_no_micropub_endpoint_returns_400(self):
        s = auth_session()
        del s["micropub_endpoint"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.post("/new/", {"content": "Hello"})
        self.assertEqual(response.status_code, 400)

    def test_post_no_access_token_redirects_to_login(self):
        # The auth middleware handles this before the view runs.
        s = auth_session()
        del s["access_token"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.post("/new/", {"content": "Hello"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])


@override_settings(STORAGES=SIMPLE_STORAGES)
class UploadMediaViewTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    def _make_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile("photo.jpg", b"fake-image-data", content_type="image/jpeg")

    def test_get_returns_405(self):
        self._auth_session()
        response = self.client.get("/api/micropub/media/")
        self.assertEqual(response.status_code, 405)

    def test_no_micropub_endpoint_returns_400(self):
        s = auth_session()
        del s["micropub_endpoint"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.post("/api/micropub/media/", {"file": self._make_file()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Micropub not available")

    def test_no_access_token_redirects_to_login(self):
        # The auth middleware handles this before the view runs.
        s = auth_session()
        del s["access_token"]
        session = self.client.session
        session.update(s)
        session.save()
        response = self.client.post("/api/micropub/media/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_no_file_returns_400(self):
        self._auth_session()
        response = self.client.post("/api/micropub/media/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "No file provided")

    @patch("microsub_client.views.micropub.query_config", return_value={"syndicate-to": []})
    def test_no_media_endpoint_returns_400(self, _mock):
        self._auth_session()
        response = self.client.post("/api/micropub/media/", {"file": self._make_file()})
        self.assertEqual(response.status_code, 400)
        self.assertIn("media endpoint", response.json()["error"].lower())

    @patch("microsub_client.views.micropub.upload_media", return_value="https://media.example/photo.jpg")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_WITH_MEDIA)
    def test_upload_success_returns_url(self, _mock_config, _mock_upload):
        self._auth_session()
        response = self.client.post("/api/micropub/media/", {"file": self._make_file()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["url"], "https://media.example/photo.jpg")

    @patch("microsub_client.views.micropub.upload_media", side_effect=micropub.MicropubError("upload failed"))
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_WITH_MEDIA)
    def test_micropub_error_returns_502(self, _mock_config, _mock_upload):
        self._auth_session()
        response = self.client.post("/api/micropub/media/", {"file": self._make_file()})
        self.assertEqual(response.status_code, 502)
        self.assertIn("upload failed", response.json()["error"])

    @patch("microsub_client.views.image_utils.maybe_convert", side_effect=ValueError("Cannot decode image"))
    def test_undecodable_image_returns_422(self, _mock_convert):
        self._auth_session()
        response = self.client.post("/api/micropub/media/", {"file": self._make_file()})
        self.assertEqual(response.status_code, 422)
        self.assertIn("Cannot decode image", response.json()["error"])

    @patch("microsub_client.views.micropub.upload_media", return_value="https://media.example/photo.jpg")
    @patch("microsub_client.views.micropub.query_config", return_value=_CONFIG_WITH_MEDIA)
    @patch("microsub_client.views.image_utils.maybe_convert")
    def test_upload_calls_maybe_convert(self, mock_convert, _mock_config, _mock_upload):
        """maybe_convert is called before forwarding the file."""
        self._auth_session()
        f = self._make_file()
        mock_convert.return_value = f
        self.client.post("/api/micropub/media/", {"file": f})
        mock_convert.assert_called_once()


@override_settings(STORAGES=SIMPLE_STORAGES)
class ConvertImageViewTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    def _make_jpeg(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), color=(200, 100, 50)).save(buf, format="JPEG")
        size = buf.tell()
        buf.seek(0)
        return InMemoryUploadedFile(buf, None, "photo.jpg", "image/jpeg", size, None)

    def _make_tiff(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), color=(50, 100, 200)).save(buf, format="TIFF")
        size = buf.tell()
        buf.seek(0)
        return InMemoryUploadedFile(buf, None, "photo.tiff", "image/tiff", size, None)

    def _make_png(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format="PNG")
        size = buf.tell()
        buf.seek(0)
        return InMemoryUploadedFile(buf, None, "photo.png", "image/png", size, None)

    def test_get_returns_405(self):
        self._auth_session()
        response = self.client.get("/api/image/convert/")
        self.assertEqual(response.status_code, 405)

    def test_unauthenticated_returns_403(self):
        # The auth middleware handles this before the view runs.
        response = self.client.post("/api/image/convert/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    def test_no_file_returns_400(self):
        self._auth_session()
        response = self.client.post("/api/image/convert/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "No file provided")

    def test_jpeg_passthrough_returns_jpeg(self):
        self._auth_session()
        response = self.client.post("/api/image/convert/", {"file": self._make_jpeg()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")

    def test_tiff_converted_to_jpeg(self):
        self._auth_session()
        response = self.client.post("/api/image/convert/", {"file": self._make_tiff()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertGreater(len(response.content), 0)

    def test_undecodable_file_returns_422(self):
        self._auth_session()
        bad = SimpleUploadedFile("bad.tiff", b"not-an-image", content_type="image/tiff")
        response = self.client.post("/api/image/convert/", {"file": bad})
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())

    def test_png_passthrough_preserves_content_type(self):
        self._auth_session()
        response = self.client.post("/api/image/convert/", {"file": self._make_png()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")


@override_settings(STORAGES=SIMPLE_STORAGES)
class ModerationViewTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    def test_mute_requires_author_url(self):
        self._auth_session()
        response = self.client.post("/api/mute/", {})
        self.assertEqual(response.status_code, 400)

    @patch("microsub_client.views.api.mute_user")
    def test_mute_calls_api(self, mock_mute):
        self._auth_session()
        response = self.client.post("/api/mute/", {"author_url": "https://alice.example/", "channel": "main"})
        self.assertEqual(response.status_code, 204)
        mock_mute.assert_called_once_with(
            "https://microsub.example/",
            "test-token",
            "https://alice.example/",
            channel="main",
        )

    @patch("microsub_client.views.api.unmute_user")
    def test_unmute_calls_api(self, mock_unmute):
        self._auth_session()
        response = self.client.post("/api/unmute/", {"author_url": "https://alice.example/", "channel": "main"})
        self.assertEqual(response.status_code, 204)
        mock_unmute.assert_called_once_with(
            "https://microsub.example/",
            "test-token",
            "https://alice.example/",
            channel="main",
        )

    @patch("microsub_client.views.api.block_user")
    def test_block_calls_api(self, mock_block):
        self._auth_session()
        response = self.client.post("/api/block/", {"author_url": "https://alice.example/"})
        self.assertEqual(response.status_code, 204)
        mock_block.assert_called_once_with(
            "https://microsub.example/",
            "test-token",
            "https://alice.example/",
        )


@override_settings(STORAGES=SIMPLE_STORAGES)
class DraftEndpointsTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    def test_save_creates_draft(self):
        self._auth_session()
        response = self.client.post("/drafts/save/", {
            "name": "Draft title",
            "content": "Draft body",
            "tags": "padd,v1",
            "photo": ["https://img.example/a.jpg"],
            "location": "geo:1,2",
        })
        self.assertEqual(response.status_code, 200)
        draft = Draft.objects.get(user_url="https://me.example/")
        self.assertEqual(draft.title, "Draft title")
        self.assertEqual(draft.content, "Draft body")
        self.assertContains(response, 'id="draft-id"')

    def test_save_updates_existing_draft(self):
        self._auth_session()
        draft = Draft.objects.create(user_url="https://me.example/", title="Old", content="Old body")
        response = self.client.post("/drafts/save/", {
            "draft_id": str(draft.pk),
            "name": "New",
            "content": "New body",
        })
        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.title, "New")
        self.assertEqual(draft.content, "New body")

    def test_delete_removes_draft(self):
        self._auth_session()
        draft = Draft.objects.create(user_url="https://me.example/", title="Delete me")
        response = self.client.post(f"/drafts/{draft.pk}/delete/", {"draft_id": str(draft.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Draft.objects.filter(pk=draft.pk).exists())
        self.assertContains(response, 'id="draft-id"')


@override_settings(STORAGES=SIMPLE_STORAGES)
class OpmlViewsTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    @patch("microsub_client.views.api.get_follows", return_value={"items": [{"url": "https://feed.example/rss", "name": "Feed"}]})
    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "main", "name": "Main"}])
    def test_export_returns_opml_attachment(self, _mock_channels, _mock_follows):
        self._auth_session()
        response = self.client.get("/opml/export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml; charset=utf-8")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertContains(response, "xmlUrl=\"https://feed.example/rss\"")

    @patch("microsub_client.views.SafeET.parse", side_effect=DefusedXmlException("forbidden"))
    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "main", "name": "Main"}])
    def test_import_handles_defusedxml_exception(self, _mock_channels, _mock_parse):
        self._auth_session()
        opml = SimpleUploadedFile("subs.opml", b"<opml></opml>", content_type="text/xml")
        response = self.client.post("/opml/import/", {"opml_file": opml, "fallback_channel": "main"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Could not parse OPML file")

    @patch("microsub_client.views.api.follow_feed")
    @patch("microsub_client.views.api.create_channel")
    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "tech", "name": "Tech"}])
    def test_import_nested_folders_flatten_to_top_level_channel(self, _mock_channels, _mock_create_channel, mock_follow):
        self._auth_session()
        opml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <body>
    <outline text="Tech">
      <outline text="Python">
        <outline type="rss" xmlUrl="https://feeds.example/python.xml" />
      </outline>
    </outline>
  </body>
</opml>"""
        opml = SimpleUploadedFile("nested.opml", opml_content, content_type="text/xml")
        response = self.client.post("/opml/import/", {"opml_file": opml})
        self.assertEqual(response.status_code, 200)
        _mock_create_channel.assert_not_called()
        mock_follow.assert_called_once_with(
            "https://microsub.example/",
            "test-token",
            "tech",
            "https://feeds.example/python.xml",
        )


@override_settings(STORAGES=SIMPLE_STORAGES)
class DiscoverViewTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    @patch("microsub_client.views.api.get_channels", return_value=[{"uid": "main", "name": "Main"}])
    def test_hot_sort_orders_by_total_interactions(self, _mock_channels):
        self._auth_session()
        e1 = CachedEntry.objects.create(url="https://post.example/1", title="One")
        e2 = CachedEntry.objects.create(url="https://post.example/2", title="Two")
        Interaction.objects.create(user_url="https://a.example/", entry=e1, kind="like")
        Interaction.objects.create(user_url="https://b.example/", entry=e1, kind="reply")
        Interaction.objects.create(user_url="https://a.example/", entry=e2, kind="like")
        response = self.client.get("/discover/?sort=hot")
        self.assertEqual(response.status_code, 200)
        page_entries = list(response.context["entries"].object_list)
        self.assertEqual(page_entries[0].url, "https://post.example/1")
        self.assertEqual(page_entries[1].url, "https://post.example/2")


@override_settings(STORAGES=SIMPLE_STORAGES)
class HarvestSettingsTests(TestCase):
    def _auth_session(self):
        session = self.client.session
        session.update(auth_session())
        session.save()

    def test_settings_can_enable_harvest_toggle(self):
        self._auth_session()
        response = self.client.post("/settings/", {
            "default_filter": "all",
            "mark_read_behavior": "explicit",
            "show_gardn_harvest": "on",
        })
        self.assertEqual(response.status_code, 302)
        settings_obj = UserSettings.objects.get(user_url="https://me.example/")
        self.assertTrue(settings_obj.show_gardn_harvest)
