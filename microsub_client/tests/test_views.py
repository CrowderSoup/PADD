from unittest.mock import patch

from django.test import TestCase, override_settings

from microsub_client import api, micropub
from microsub_client.models import Broadcast, Interaction

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
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        session = self.client.session
        self.assertEqual(session["access_token"], "tok123")
        self.assertEqual(session["user_name"], "Jane")
        self.assertNotIn("auth_state", session)
        self.assertNotIn("code_verifier", session)


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
    def test_missing_content_returns_400(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.post("/api/micropub/reply/", {"entry_url": "https://example.com"})
        self.assertEqual(response.status_code, 400)

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
        response = self.client.get("/admin/broadcasts/")
        self.assertEqual(response.status_code, 403)

    def test_admin_view_accessible_by_admin(self):
        session = self.client.session
        session.update(self._admin_session())
        session.save()
        response = self.client.get("/admin/broadcasts/")
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
        session = self.client.session
        self.assertIn(b.id, session["dismissed_broadcasts"])

    def test_dismiss_get_returns_405(self):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/api/broadcast/1/dismiss/")
        self.assertEqual(response.status_code, 405)


@override_settings(STORAGES=SIMPLE_STORAGES)
class IndexViewTests(TestCase):
    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "home", "name": "Home"},
    ])
    def test_redirects_to_first_channel(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/")
        self.assertRedirects(response, "/channel/home/", fetch_redirect_response=False)

    @patch("microsub_client.views.api.get_channels", return_value=[
        {"uid": "default", "name": "Default"},
    ])
    def test_single_channel_redirects(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/")
        self.assertRedirects(response, "/channel/default/", fetch_redirect_response=False)

    @patch("microsub_client.views.api.get_channels", side_effect=api.MicrosubError("fail"))
    def test_api_error_redirects_to_login(self, _mock):
        session = self.client.session
        session.update(auth_session())
        session.save()
        response = self.client.get("/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)


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
        session = self.client.session
        self.assertEqual(session["default_filter"], "unread")
