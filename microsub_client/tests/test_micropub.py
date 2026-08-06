from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
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


class MicropubPostJsonTests(TestCase):
    @patch("microsub_client.micropub.requests.post")
    def test_success_sends_json_body(self, mock_post):
        mock_post.return_value = Mock(status_code=204, headers={})
        micropub._post_json("https://mp.example/", "token", {"action": "update"})
        mock_post.assert_called_once_with(
            "https://mp.example/",
            allow_redirects=False,
            headers={"Authorization": "Bearer token"},
            json={"action": "update"},
            timeout=15,
        )

    @patch("microsub_client.micropub.requests.post")
    def test_204_no_content_is_success(self, mock_post):
        mock_post.return_value = Mock(status_code=204, headers={})
        result = micropub._post_json("https://mp.example/", "token", {"action": "update"})
        self.assertEqual(result, "")

    @patch("microsub_client.micropub.requests.post")
    def test_401_raises_auth_error(self, mock_post):
        mock_post.return_value = Mock(status_code=401, headers={})
        with self.assertRaises(micropub.AuthenticationError):
            micropub._post_json("https://mp.example/", "token", {"action": "update"})

    @patch("microsub_client.micropub.requests.post")
    def test_400_raises_micropub_error(self, mock_post):
        mock_post.return_value = Mock(status_code=400, text="Invalid replace payload", headers={})
        with self.assertRaises(micropub.MicropubError):
            micropub._post_json("https://mp.example/", "token", {"action": "update"})

    @patch("microsub_client.micropub.requests.post")
    def test_network_error(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException("fail")
        with self.assertRaises(micropub.MicropubError):
            micropub._post_json("https://mp.example/", "token", {"action": "update"})


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


class CreatePostTests(TestCase):
    @patch("microsub_client.micropub._post")
    def test_minimal_note(self, mock_post):
        mock_post.return_value = "https://me.example/post/1"
        result = micropub.create_post("https://mp.example/", "token", "Hello world")
        data = mock_post.call_args.args[2]
        self.assertIn(("h", "entry"), data)
        self.assertIn(("content", "Hello world"), data)
        self.assertEqual(result, "https://me.example/post/1")

    @patch("microsub_client.micropub._post")
    def test_with_name(self, mock_post):
        mock_post.return_value = ""
        micropub.create_post("https://mp.example/", "token", "Body", name="My Article")
        data = mock_post.call_args.args[2]
        self.assertIn(("name", "My Article"), data)

    @patch("microsub_client.micropub._post")
    def test_category_sends_multiple_tuples(self, mock_post):
        mock_post.return_value = ""
        micropub.create_post("https://mp.example/", "token", "Tagged", category=["python", "web"])
        data = mock_post.call_args.args[2]
        self.assertIn(("category[]", "python"), data)
        self.assertIn(("category[]", "web"), data)
        for k, v in data:
            if k == "category[]":
                self.assertIsInstance(v, str)

    @patch("microsub_client.micropub._post")
    def test_photo_sends_multiple_tuples(self, mock_post):
        mock_post.return_value = ""
        micropub.create_post(
            "https://mp.example/", "token", "Photos",
            photo=["https://example.com/a.jpg", "https://example.com/b.jpg"],
        )
        data = mock_post.call_args.args[2]
        self.assertIn(("photo[]", "https://example.com/a.jpg"), data)
        self.assertIn(("photo[]", "https://example.com/b.jpg"), data)
        for k, v in data:
            if k == "photo[]":
                self.assertIsInstance(v, str)

    @patch("microsub_client.micropub._post")
    def test_syndicate_to_sends_multiple_tuples(self, mock_post):
        mock_post.return_value = ""
        micropub.create_post(
            "https://mp.example/", "token", "Syndicated",
            syndicate_to=["https://twitter.com/", "https://mastodon.social/"],
        )
        data = mock_post.call_args.args[2]
        self.assertIn(("syndicate-to[]", "https://twitter.com/"), data)
        self.assertIn(("syndicate-to[]", "https://mastodon.social/"), data)

    @patch("microsub_client.micropub._post")
    def test_all_fields_no_list_valued_tuples(self, mock_post):
        """Regression: category[] and photo[] must be flat tuples even when syndicate_to is set."""
        mock_post.return_value = ""
        micropub.create_post(
            "https://mp.example/", "token", "Full post",
            name="Full Article",
            category=["python", "web"],
            photo=["https://example.com/a.jpg", "https://example.com/b.jpg"],
            location="geo:37.123,-122.456",
            syndicate_to=["https://twitter.com/", "https://bsky.app/"],
        )
        data = mock_post.call_args.args[2]
        for k, v in data:
            self.assertIsInstance(v, str, f"Field {k!r} has non-string value: {v!r}")
        self.assertIn(("h", "entry"), data)
        self.assertIn(("content", "Full post"), data)
        self.assertIn(("name", "Full Article"), data)
        self.assertIn(("category[]", "python"), data)
        self.assertIn(("category[]", "web"), data)
        self.assertIn(("photo[]", "https://example.com/a.jpg"), data)
        self.assertIn(("photo[]", "https://example.com/b.jpg"), data)
        self.assertIn(("location", "geo:37.123,-122.456"), data)
        self.assertIn(("syndicate-to[]", "https://twitter.com/"), data)
        self.assertIn(("syndicate-to[]", "https://bsky.app/"), data)

    @patch("microsub_client.micropub._post")
    def test_none_fields_omitted(self, mock_post):
        mock_post.return_value = ""
        micropub.create_post("https://mp.example/", "token", "Simple note")
        data = mock_post.call_args.args[2]
        keys = [k for k, _ in data]
        self.assertNotIn("name", keys)
        self.assertNotIn("category[]", keys)
        self.assertNotIn("photo[]", keys)
        self.assertNotIn("location", keys)
        self.assertNotIn("syndicate-to[]", keys)

    @patch("microsub_client.micropub._post")
    def test_with_location(self, mock_post):
        mock_post.return_value = ""
        micropub.create_post("https://mp.example/", "token", "Here", location="geo:37.0,-122.0")
        data = mock_post.call_args.args[2]
        self.assertIn(("location", "geo:37.0,-122.0"), data)


class UpdatePostTests(TestCase):
    @patch("microsub_client.micropub._post_json")
    def test_replace_only(self, mock_post_json):
        mock_post_json.return_value = ""
        micropub.update_post(
            "https://mp.example/", "token", "https://me.example/post/1",
            replace={"content": ["Updated body"]},
        )
        mock_post_json.assert_called_once_with(
            "https://mp.example/", "token",
            {
                "action": "update",
                "url": "https://me.example/post/1",
                "replace": {"content": ["Updated body"]},
            },
        )

    @patch("microsub_client.micropub._post_json")
    def test_replace_add_and_delete_together(self, mock_post_json):
        mock_post_json.return_value = ""
        micropub.update_post(
            "https://mp.example/", "token", "https://me.example/post/1",
            replace={"name": ["New title"]},
            add={"photo": ["https://media.example/new.jpg"]},
            delete={"photo": ["https://media.example/old.jpg"]},
        )
        payload = mock_post_json.call_args.args[2]
        self.assertEqual(payload["action"], "update")
        self.assertEqual(payload["url"], "https://me.example/post/1")
        self.assertEqual(payload["replace"], {"name": ["New title"]})
        self.assertEqual(payload["add"], {"photo": ["https://media.example/new.jpg"]})
        self.assertEqual(payload["delete"], {"photo": ["https://media.example/old.jpg"]})

    @patch("microsub_client.micropub._post_json")
    def test_none_fields_omitted(self, mock_post_json):
        mock_post_json.return_value = ""
        micropub.update_post("https://mp.example/", "token", "https://me.example/post/1")
        payload = mock_post_json.call_args.args[2]
        self.assertNotIn("replace", payload)
        self.assertNotIn("add", payload)
        self.assertNotIn("delete", payload)


class QueryConfigTests(TestCase):
    @patch("microsub_client.micropub.requests.get")
    def test_returns_parsed_json(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=lambda: {"media-endpoint": "https://media.example/", "syndicate-to": []},
        )
        result = micropub.query_config("https://mp.example/", "token")
        self.assertEqual(result["media-endpoint"], "https://media.example/")
        mock_get.assert_called_once_with(
            "https://mp.example/?q=config",
            headers={"Authorization": "Bearer token"},
            timeout=15,
            allow_redirects=False,
        )

    @patch("microsub_client.micropub.requests.get")
    def test_401_raises_auth_error(self, mock_get):
        mock_get.return_value = Mock(status_code=401)
        with self.assertRaises(micropub.AuthenticationError):
            micropub.query_config("https://mp.example/", "token")

    @patch("microsub_client.micropub.requests.get")
    def test_non_200_raises_micropub_error(self, mock_get):
        mock_get.return_value = Mock(status_code=500, text="Server error")
        with self.assertRaises(micropub.MicropubError):
            micropub.query_config("https://mp.example/", "token")

    @patch("microsub_client.micropub.requests.get")
    def test_network_error_raises_micropub_error(self, mock_get):
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("timeout")
        with self.assertRaises(micropub.MicropubError):
            micropub.query_config("https://mp.example/", "token")

    @patch("microsub_client.micropub.requests.get")
    def test_invalid_json_raises_micropub_error(self, mock_get):
        mock_get.return_value = Mock(status_code=200)
        mock_get.return_value.json.side_effect = ValueError("bad json")
        with self.assertRaises(micropub.MicropubError):
            micropub.query_config("https://mp.example/", "token")


class FetchSourceTests(TestCase):
    @patch("microsub_client.micropub.requests.get")
    def test_returns_unwrapped_properties(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=lambda: {"properties": {"content": ["Hello"], "category": ["python"]}},
        )
        result = micropub.fetch_source(
            "https://mp.example/", "token", "https://me.example/post/1"
        )
        self.assertEqual(result, {"content": ["Hello"], "category": ["python"]})

    @patch("microsub_client.micropub.requests.get")
    def test_sends_q_source_and_url(self, mock_get):
        mock_get.return_value = Mock(status_code=200, json=lambda: {"properties": {}})
        micropub.fetch_source("https://mp.example/", "token", "https://me.example/post/1")
        called_url = mock_get.call_args.args[0]
        self.assertIn("q=source", called_url)
        self.assertIn("url=https%3A%2F%2Fme.example%2Fpost%2F1", called_url)

    @patch("microsub_client.micropub.requests.get")
    def test_properties_filter_sends_properties_params(self, mock_get):
        mock_get.return_value = Mock(status_code=200, json=lambda: {"properties": {}})
        micropub.fetch_source(
            "https://mp.example/", "token", "https://me.example/post/1",
            properties=["content", "category"],
        )
        called_url = mock_get.call_args.args[0]
        self.assertIn("properties%5B%5D=content", called_url)
        self.assertIn("properties%5B%5D=category", called_url)

    @patch("microsub_client.micropub.requests.get")
    def test_401_raises_auth_error(self, mock_get):
        mock_get.return_value = Mock(status_code=401)
        with self.assertRaises(micropub.AuthenticationError):
            micropub.fetch_source("https://mp.example/", "token", "https://me.example/post/1")

    @patch("microsub_client.micropub.requests.get")
    def test_non_200_raises_micropub_error(self, mock_get):
        mock_get.return_value = Mock(status_code=404, text="Post not found")
        with self.assertRaises(micropub.MicropubError):
            micropub.fetch_source("https://mp.example/", "token", "https://me.example/post/1")

    @patch("microsub_client.micropub.requests.get")
    def test_network_error_raises_micropub_error(self, mock_get):
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("timeout")
        with self.assertRaises(micropub.MicropubError):
            micropub.fetch_source("https://mp.example/", "token", "https://me.example/post/1")


class UploadMediaTests(TestCase):
    def _make_file(self):
        return SimpleUploadedFile("photo.jpg", b"fake-image-data", content_type="image/jpeg")

    @patch("microsub_client.micropub.requests.post")
    def test_success_returns_location_url(self, mock_post):
        mock_post.return_value = Mock(
            status_code=201,
            headers={"Location": "https://media.example/photo.jpg"},
        )
        result = micropub.upload_media("https://media.example/", "token", self._make_file())
        self.assertEqual(result, "https://media.example/photo.jpg")

    @patch("microsub_client.micropub.requests.post")
    def test_202_accepted_returns_location(self, mock_post):
        mock_post.return_value = Mock(
            status_code=202,
            headers={"Location": "https://media.example/photo.jpg"},
        )
        result = micropub.upload_media("https://media.example/", "token", self._make_file())
        self.assertEqual(result, "https://media.example/photo.jpg")

    @patch("microsub_client.micropub.requests.post")
    def test_missing_location_header_raises_error(self, mock_post):
        mock_post.return_value = Mock(status_code=201, headers={})
        with self.assertRaises(micropub.MicropubError):
            micropub.upload_media("https://media.example/", "token", self._make_file())

    @patch("microsub_client.micropub.requests.post")
    def test_401_raises_auth_error(self, mock_post):
        mock_post.return_value = Mock(status_code=401, headers={})
        with self.assertRaises(micropub.AuthenticationError):
            micropub.upload_media("https://media.example/", "token", self._make_file())

    @patch("microsub_client.micropub.requests.post")
    def test_non_201_raises_micropub_error(self, mock_post):
        mock_post.return_value = Mock(status_code=400, text="Bad Request", headers={})
        with self.assertRaises(micropub.MicropubError):
            micropub.upload_media("https://media.example/", "token", self._make_file())

    @patch("microsub_client.micropub.requests.post")
    def test_network_error_raises_micropub_error(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException("timeout")
        with self.assertRaises(micropub.MicropubError):
            micropub.upload_media("https://media.example/", "token", self._make_file())
