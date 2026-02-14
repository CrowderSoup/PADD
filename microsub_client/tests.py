from unittest.mock import patch

from django.test import TestCase


class ClientIdMetadataTests(TestCase):
    def test_client_id_metadata_is_public_and_contains_expected_fields(self):
        response = self.client.get("/id")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        body = response.json()
        self.assertEqual(body["client_id"], "http://testserver/id")
        self.assertEqual(body["client_name"], "PADD")
        self.assertEqual(body["client_uri"], "http://testserver/")
        self.assertTrue(body["logo_uri"].startswith("http://testserver/static/logo"))
        self.assertTrue(body["logo_uri"].endswith(".svg"))
        self.assertEqual(body["redirect_uris"], ["http://testserver/login/callback/"])
        self.assertEqual(body["scope"], "read follow channels create")


class LoginClientIdTests(TestCase):
    @patch("microsub_client.views.generate_pkce_pair", return_value=("verifier", "challenge"))
    @patch(
        "microsub_client.views.discover_endpoints",
        return_value={
            "authorization_endpoint": "https://auth.example/authorize",
            "token_endpoint": "https://auth.example/token",
            "microsub": "https://user.example/microsub",
            "micropub": "https://user.example/micropub",
        },
    )
    @patch("microsub_client.views.build_authorization_url", return_value="https://auth.example/next")
    def test_login_uses_client_id_metadata_endpoint(
        self,
        build_authorization_url_mock,
        _discover_endpoints_mock,
        _generate_pkce_pair_mock,
    ):
        response = self.client.post("/login/", {"url": "https://user.example/"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://auth.example/next")
        self.assertEqual(
            build_authorization_url_mock.call_args.kwargs["client_id"],
            "http://testserver/id",
        )
