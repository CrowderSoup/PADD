from unittest.mock import Mock, patch

from django.test import TestCase

from microsub_client.auth import (
    build_authorization_url,
    discover_endpoints,
    exchange_code_for_token,
    fetch_hcard,
    generate_pkce_pair,
)


class FetchHcardTests(TestCase):
    @patch("microsub_client.auth.requests.get")
    def test_returns_name_and_photo(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            text='''
            <div class="h-card">
                <a class="p-name u-url" href="https://me.example/">Jane Doe</a>
                <img class="u-photo" src="https://me.example/photo.jpg">
            </div>
            ''',
        )
        mock_get.return_value.raise_for_status = Mock()
        result = fetch_hcard("https://me.example/")
        self.assertEqual(result["name"], "Jane Doe")
        self.assertEqual(result["photo"], "https://me.example/photo.jpg")

    @patch("microsub_client.auth.requests.get")
    def test_prepends_https_when_missing(self, mock_get):
        mock_get.return_value = Mock(status_code=200, text="<html></html>")
        mock_get.return_value.raise_for_status = Mock()
        fetch_hcard("me.example")
        mock_get.assert_called_once()
        self.assertTrue(mock_get.call_args[0][0].startswith("https://"))

    @patch("microsub_client.auth.requests.get")
    def test_returns_none_on_network_error(self, mock_get):
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("fail")
        result = fetch_hcard("https://me.example/")
        self.assertIsNone(result["name"])
        self.assertIsNone(result["photo"])

    @patch("microsub_client.auth.requests.get")
    def test_no_hcard_returns_none(self, mock_get):
        mock_get.return_value = Mock(status_code=200, text="<html><body>no card</body></html>")
        mock_get.return_value.raise_for_status = Mock()
        result = fetch_hcard("https://me.example/")
        self.assertIsNone(result["name"])
        self.assertIsNone(result["photo"])


class DiscoverEndpointsTests(TestCase):
    @patch("microsub_client.auth.requests.get")
    def test_discovers_from_html_link_tags(self, mock_get):
        html = '''
        <html><head>
        <link rel="authorization_endpoint" href="https://auth.example/auth">
        <link rel="token_endpoint" href="https://auth.example/token">
        <link rel="microsub" href="https://reader.example/microsub">
        <link rel="micropub" href="https://pub.example/micropub">
        </head></html>
        '''
        mock_get.return_value = Mock(status_code=200, text=html, headers={})
        mock_get.return_value.raise_for_status = Mock()
        result = discover_endpoints("https://user.example/")
        self.assertEqual(result["authorization_endpoint"], "https://auth.example/auth")
        self.assertEqual(result["token_endpoint"], "https://auth.example/token")
        self.assertEqual(result["microsub"], "https://reader.example/microsub")
        self.assertEqual(result["micropub"], "https://pub.example/micropub")

    @patch("microsub_client.auth.requests.get")
    def test_discovers_from_http_link_headers(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            text="<html></html>",
            headers={
                "Link": '<https://auth.example/auth>; rel="authorization_endpoint", '
                        '<https://auth.example/token>; rel="token_endpoint"',
            },
        )
        mock_get.return_value.raise_for_status = Mock()
        result = discover_endpoints("https://user.example/")
        self.assertEqual(result["authorization_endpoint"], "https://auth.example/auth")
        self.assertEqual(result["token_endpoint"], "https://auth.example/token")

    @patch("microsub_client.auth.requests.get")
    def test_prepends_https_and_trailing_slash(self, mock_get):
        mock_get.return_value = Mock(status_code=200, text="<html></html>", headers={})
        mock_get.return_value.raise_for_status = Mock()
        discover_endpoints("user.example")
        self.assertEqual(mock_get.call_args[0][0], "https://user.example/")

    @patch("microsub_client.auth.requests.get")
    def test_raises_on_network_error(self, mock_get):
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("fail")
        with self.assertRaises(ValueError):
            discover_endpoints("https://user.example/")

    @patch("microsub_client.auth.requests.get")
    def test_html_overrides_headers(self, mock_get):
        html = '<link rel="authorization_endpoint" href="https://html.example/auth">'
        mock_get.return_value = Mock(
            status_code=200,
            text=html,
            headers={
                "Link": '<https://header.example/auth>; rel="authorization_endpoint"',
            },
        )
        mock_get.return_value.raise_for_status = Mock()
        result = discover_endpoints("https://user.example/")
        self.assertEqual(result["authorization_endpoint"], "https://html.example/auth")

    @patch("microsub_client.auth.requests.get")
    def test_reversed_attribute_order(self, mock_get):
        html = '<link href="https://auth.example/auth" rel="authorization_endpoint">'
        mock_get.return_value = Mock(status_code=200, text=html, headers={})
        mock_get.return_value.raise_for_status = Mock()
        result = discover_endpoints("https://user.example/")
        self.assertEqual(result["authorization_endpoint"], "https://auth.example/auth")


class GeneratePkcePairTests(TestCase):
    def test_returns_two_strings(self):
        verifier, challenge = generate_pkce_pair()
        self.assertIsInstance(verifier, str)
        self.assertIsInstance(challenge, str)

    def test_verifier_is_long_enough(self):
        verifier, _ = generate_pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)

    def test_challenge_has_no_padding(self):
        _, challenge = generate_pkce_pair()
        self.assertNotIn("=", challenge)

    def test_different_each_call(self):
        pair1 = generate_pkce_pair()
        pair2 = generate_pkce_pair()
        self.assertNotEqual(pair1, pair2)


class BuildAuthorizationUrlTests(TestCase):
    def test_url_contains_all_params(self):
        url = build_authorization_url(
            "https://auth.example/authorize",
            me="https://me.example/",
            redirect_uri="https://app.example/callback",
            state="test-state",
            client_id="https://app.example/id",
            code_challenge="test-challenge",
        )
        self.assertTrue(url.startswith("https://auth.example/authorize?"))
        self.assertIn("me=", url)
        self.assertIn("client_id=", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("state=test-state", url)
        self.assertIn("code_challenge=test-challenge", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("response_type=code", url)
        self.assertIn("scope=read+follow+channels+create", url)


class ExchangeCodeForTokenTests(TestCase):
    @patch("microsub_client.auth.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {"access_token": "tok123", "me": "https://me.example/"},
        )
        mock_post.return_value.raise_for_status = Mock()
        result = exchange_code_for_token(
            "https://auth.example/token", "code123",
            "https://app.example/callback", "https://app.example/id", "verifier",
        )
        self.assertEqual(result["access_token"], "tok123")

    @patch("microsub_client.auth.requests.post")
    def test_raises_on_missing_token(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {"error": "invalid_grant"},
        )
        mock_post.return_value.raise_for_status = Mock()
        with self.assertRaises(ValueError):
            exchange_code_for_token(
                "https://auth.example/token", "code123",
                "https://app.example/callback", "https://app.example/id", "verifier",
            )

    @patch("microsub_client.auth.requests.post")
    def test_raises_on_network_error(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException("fail")
        with self.assertRaises(ValueError):
            exchange_code_for_token(
                "https://auth.example/token", "code123",
                "https://app.example/callback", "https://app.example/id", "verifier",
            )
