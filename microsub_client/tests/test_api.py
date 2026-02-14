from unittest.mock import Mock, patch

from django.test import TestCase

from microsub_client import api


class ApiRequestTests(TestCase):
    @patch("microsub_client.api.requests.request")
    def test_success_returns_json(self, mock_req):
        mock_req.return_value = Mock(
            status_code=200, ok=True, content=b'{"channels":[]}',
            json=lambda: {"channels": []},
        )
        result = api._request("GET", "https://api.example/", "token")
        self.assertEqual(result, {"channels": []})

    @patch("microsub_client.api.requests.request")
    def test_204_returns_empty_dict(self, mock_req):
        mock_req.return_value = Mock(status_code=204, ok=True, content=b"")
        result = api._request("GET", "https://api.example/", "token")
        self.assertEqual(result, {})

    @patch("microsub_client.api.requests.request")
    def test_401_raises_auth_error(self, mock_req):
        mock_req.return_value = Mock(status_code=401, ok=False)
        with self.assertRaises(api.AuthenticationError):
            api._request("GET", "https://api.example/", "token")

    @patch("microsub_client.api.requests.request")
    def test_500_raises_microsub_error(self, mock_req):
        mock_req.return_value = Mock(status_code=500, ok=False)
        with self.assertRaises(api.MicrosubError):
            api._request("GET", "https://api.example/", "token")

    @patch("microsub_client.api.requests.request")
    def test_network_error_raises_microsub_error(self, mock_req):
        from requests.exceptions import RequestException
        mock_req.side_effect = RequestException("fail")
        with self.assertRaises(api.MicrosubError):
            api._request("GET", "https://api.example/", "token")

    @patch("microsub_client.api.requests.request")
    def test_bearer_token_in_header(self, mock_req):
        mock_req.return_value = Mock(status_code=200, ok=True, content=b'{}', json=lambda: {})
        api._request("GET", "https://api.example/", "my-token")
        headers = mock_req.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer my-token")


class GetChannelsTests(TestCase):
    @patch("microsub_client.api._request")
    def test_returns_channels(self, mock_req):
        mock_req.return_value = {"channels": [{"uid": "default", "name": "Home"}]}
        result = api.get_channels("https://api.example/", "token")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["uid"], "default")

    @patch("microsub_client.api._request")
    def test_returns_empty_when_no_channels(self, mock_req):
        mock_req.return_value = {}
        result = api.get_channels("https://api.example/", "token")
        self.assertEqual(result, [])


class GetTimelineTests(TestCase):
    @patch("microsub_client.api._request")
    def test_passes_channel_uid(self, mock_req):
        mock_req.return_value = {"items": []}
        api.get_timeline("https://api.example/", "token", "notifications")
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["channel"], "notifications")
        self.assertEqual(params["action"], "timeline")

    @patch("microsub_client.api._request")
    def test_includes_after_when_given(self, mock_req):
        mock_req.return_value = {}
        api.get_timeline("https://api.example/", "token", "default", after="cursor123")
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["after"], "cursor123")

    @patch("microsub_client.api._request")
    def test_no_after_when_none(self, mock_req):
        mock_req.return_value = {}
        api.get_timeline("https://api.example/", "token", "default")
        params = mock_req.call_args[1]["params"]
        self.assertNotIn("after", params)

    @patch("microsub_client.api._request")
    def test_is_read_true(self, mock_req):
        mock_req.return_value = {}
        api.get_timeline("https://api.example/", "token", "default", is_read=True)
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["is_read"], "true")

    @patch("microsub_client.api._request")
    def test_is_read_false(self, mock_req):
        mock_req.return_value = {}
        api.get_timeline("https://api.example/", "token", "default", is_read=False)
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["is_read"], "false")


class MarkReadTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.mark_read("https://api.example/", "token", "ch1", "entry1")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "timeline")
        self.assertEqual(data["method"], "mark_read")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["entry[]"], "entry1")
