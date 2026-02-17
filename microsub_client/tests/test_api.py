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
    def test_sends_correct_data_single_string(self, mock_req):
        mock_req.return_value = {}
        api.mark_read("https://api.example/", "token", "ch1", "entry1")
        data = mock_req.call_args[1]["data"]
        data_dict = {}
        entry_list = []
        for key, val in data:
            if key == "entry[]":
                entry_list.append(val)
            else:
                data_dict[key] = val
        self.assertEqual(data_dict["action"], "timeline")
        self.assertEqual(data_dict["method"], "mark_read")
        self.assertEqual(data_dict["channel"], "ch1")
        self.assertEqual(entry_list, ["entry1"])

    @patch("microsub_client.api._request")
    def test_sends_correct_data_multiple_entries(self, mock_req):
        mock_req.return_value = {}
        api.mark_read("https://api.example/", "token", "ch1", ["e1", "e2", "e3"])
        data = mock_req.call_args[1]["data"]
        entry_list = [val for key, val in data if key == "entry[]"]
        self.assertEqual(entry_list, ["e1", "e2", "e3"])


class MarkUnreadTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.mark_unread("https://api.example/", "token", "ch1", "entry1")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "timeline")
        self.assertEqual(data["method"], "mark_unread")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["entry[]"], "entry1")


class RemoveEntryTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.remove_entry("https://api.example/", "token", "ch1", "entry1")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "timeline")
        self.assertEqual(data["method"], "remove")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["entry[]"], "entry1")


class CreateChannelTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {"uid": "new-ch", "name": "New Channel"}
        result = api.create_channel("https://api.example/", "token", "New Channel")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "channels")
        self.assertEqual(data["name"], "New Channel")
        self.assertEqual(result["uid"], "new-ch")


class UpdateChannelTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.update_channel("https://api.example/", "token", "ch1", "Renamed")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "channels")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["name"], "Renamed")


class DeleteChannelTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.delete_channel("https://api.example/", "token", "ch1")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "channels")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["method"], "delete")


class OrderChannelsTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.order_channels("https://api.example/", "token", ["ch1", "ch2", "ch3"])
        data = mock_req.call_args[1]["data"]
        # data is a list of tuples for repeated keys
        data_dict = {}
        channels_list = []
        for key, val in data:
            if key == "channels[]":
                channels_list.append(val)
            else:
                data_dict[key] = val
        self.assertEqual(data_dict["action"], "channels")
        self.assertEqual(data_dict["method"], "order")
        self.assertEqual(channels_list, ["ch1", "ch2", "ch3"])


class SearchFeedsTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {"results": []}
        api.search_feeds("https://api.example/", "token", "example.com")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "search")
        self.assertEqual(data["query"], "example.com")


class PreviewFeedTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_params(self, mock_req):
        mock_req.return_value = {"items": []}
        api.preview_feed("https://api.example/", "token", "https://feed.example/")
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["action"], "preview")
        self.assertEqual(params["url"], "https://feed.example/")


class GetFollowsTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_params(self, mock_req):
        mock_req.return_value = {"items": []}
        api.get_follows("https://api.example/", "token", "ch1")
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["action"], "follow")
        self.assertEqual(params["channel"], "ch1")


class FollowFeedTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.follow_feed("https://api.example/", "token", "ch1", "https://feed.example/")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "follow")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["url"], "https://feed.example/")


class UnfollowFeedTests(TestCase):
    @patch("microsub_client.api._request")
    def test_sends_correct_data(self, mock_req):
        mock_req.return_value = {}
        api.unfollow_feed("https://api.example/", "token", "ch1", "https://feed.example/")
        data = mock_req.call_args[1]["data"]
        self.assertEqual(data["action"], "unfollow")
        self.assertEqual(data["channel"], "ch1")
        self.assertEqual(data["url"], "https://feed.example/")
