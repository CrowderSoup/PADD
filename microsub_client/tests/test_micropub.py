from unittest.mock import Mock, patch

from django.test import TestCase

from microsub_client import micropub


class MicropubPostTests(TestCase):
    @patch("microsub_client.micropub.requests.post")
    def test_success_returns_location(self, mock_post):
        mock_post.return_value = Mock(
            status_code=201, headers={"Location": "https://me.example/post/1"}
        )
        result = micropub._post("https://mp.example/", "token", {"h": "entry"})
        self.assertEqual(result, "https://me.example/post/1")

    @patch("microsub_client.micropub.requests.post")
    def test_202_accepted(self, mock_post):
        mock_post.return_value = Mock(status_code=202, headers={})
        result = micropub._post("https://mp.example/", "token", {"h": "entry"})
        self.assertEqual(result, "")

    @patch("microsub_client.micropub.requests.post")
    def test_401_raises_auth_error(self, mock_post):
        mock_post.return_value = Mock(status_code=401)
        with self.assertRaises(micropub.AuthenticationError):
            micropub._post("https://mp.example/", "token", {"h": "entry"})

    @patch("microsub_client.micropub.requests.post")
    def test_400_raises_micropub_error(self, mock_post):
        mock_post.return_value = Mock(status_code=400, text="Bad Request")
        with self.assertRaises(micropub.MicropubError):
            micropub._post("https://mp.example/", "token", {"h": "entry"})

    @patch("microsub_client.micropub.requests.post")
    def test_network_error(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException("fail")
        with self.assertRaises(micropub.MicropubError):
            micropub._post("https://mp.example/", "token", {"h": "entry"})


class MicropubLikeTests(TestCase):
    @patch("microsub_client.micropub._post")
    def test_like_sends_correct_data(self, mock_post):
        mock_post.return_value = "https://me.example/like/1"
        result = micropub.like("https://mp.example/", "token", "https://post.example/1")
        mock_post.assert_called_once_with(
            "https://mp.example/", "token",
            {"h": "entry", "like-of": "https://post.example/1"},
        )
        self.assertEqual(result, "https://me.example/like/1")


class MicropubRepostTests(TestCase):
    @patch("microsub_client.micropub._post")
    def test_repost_sends_correct_data(self, mock_post):
        mock_post.return_value = ""
        micropub.repost("https://mp.example/", "token", "https://post.example/1")
        mock_post.assert_called_once_with(
            "https://mp.example/", "token",
            {"h": "entry", "repost-of": "https://post.example/1"},
        )


class MicropubReplyTests(TestCase):
    @patch("microsub_client.micropub._post")
    def test_reply_sends_correct_data(self, mock_post):
        mock_post.return_value = ""
        micropub.reply("https://mp.example/", "token", "https://post.example/1", "Great post!")
        mock_post.assert_called_once_with(
            "https://mp.example/", "token",
            {"h": "entry", "in-reply-to": "https://post.example/1", "content": "Great post!"},
        )
