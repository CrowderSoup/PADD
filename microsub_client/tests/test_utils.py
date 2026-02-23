from datetime import datetime, timedelta, timezone

from django.test import TestCase
from django.utils.safestring import SafeData

from microsub_client.utils import format_datetime, get_entry_type, sanitize_content


class SanitizeContentTests(TestCase):
    def test_empty_string_returns_empty(self):
        self.assertEqual(sanitize_content(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(sanitize_content(None), "")

    def test_allowed_tags_pass_through(self):
        html = '<p>Hello <strong>world</strong></p>'
        self.assertEqual(sanitize_content(html), html)

    def test_script_tags_stripped(self):
        result = sanitize_content('<script>alert("xss")</script>Hello')
        self.assertNotIn("<script>", result)
        self.assertIn("Hello", result)

    def test_img_with_allowed_attrs(self):
        html = '<img src="pic.jpg" alt="A pic" width="100">'
        self.assertEqual(sanitize_content(html), html)

    def test_img_strips_onerror(self):
        html = '<img src="pic.jpg" onerror="alert(1)">'
        result = sanitize_content(html)
        self.assertNotIn("onerror", result)
        self.assertIn('src="pic.jpg"', result)

    def test_link_with_allowed_attrs(self):
        html = '<a href="https://example.com" title="Example" rel="nofollow">link</a>'
        self.assertEqual(sanitize_content(html), html)

    def test_disallowed_tags_stripped(self):
        result = sanitize_content('<style>body{}</style><p>text</p>')
        self.assertNotIn("<style>", result)
        self.assertIn("<p>text</p>", result)

    def test_returns_marked_safe(self):
        result = sanitize_content("<p>safe</p>")
        self.assertIsInstance(result, SafeData)


class GetEntryTypeTests(TestCase):
    def test_like(self):
        self.assertEqual(get_entry_type({"like-of": "http://example.com"}), "like")

    def test_repost(self):
        self.assertEqual(get_entry_type({"repost-of": "http://example.com"}), "repost")

    def test_reply(self):
        self.assertEqual(get_entry_type({"in-reply-to": "http://example.com"}), "reply")

    def test_bookmark(self):
        self.assertEqual(get_entry_type({"bookmark-of": "http://example.com"}), "bookmark")

    def test_photo(self):
        self.assertEqual(get_entry_type({"photo": "http://example.com/pic.jpg"}), "photo")

    def test_article_with_distinct_name(self):
        entry = {
            "name": "My Long Article Title",
            "content": {"text": "Some body text that is different"},
        }
        self.assertEqual(get_entry_type(entry), "article")

    def test_note_when_name_matches_content(self):
        entry = {
            "name": "Short note text",
            "content": {"text": "Short note text"},
        }
        self.assertEqual(get_entry_type(entry), "note")

    def test_article_with_string_content(self):
        entry = {
            "name": "My Long Article Title",
            "content": "Some body text that is different",
        }
        self.assertEqual(get_entry_type(entry), "article")

    def test_note_with_string_content_matching_name(self):
        entry = {
            "name": "Short note text",
            "content": "Short note text",
        }
        self.assertEqual(get_entry_type(entry), "note")

    def test_note_default(self):
        self.assertEqual(get_entry_type({"content": {"text": "Just a note"}}), "note")

    def test_note_empty_entry(self):
        self.assertEqual(get_entry_type({}), "note")

    def test_priority_like_over_repost(self):
        entry = {"like-of": "http://a.com", "repost-of": "http://b.com"}
        self.assertEqual(get_entry_type(entry), "like")


class FormatDatetimeTests(TestCase):
    def test_empty_string(self):
        self.assertEqual(format_datetime(""), "")

    def test_none(self):
        self.assertEqual(format_datetime(None), "")

    def test_just_now(self):
        now = datetime.now(timezone.utc).isoformat()
        self.assertEqual(format_datetime(now), "just now")

    def test_minutes_ago(self):
        t = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertEqual(format_datetime(t), "5m ago")

    def test_hours_ago(self):
        t = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertEqual(format_datetime(t), "3h ago")

    def test_yesterday(self):
        t = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.assertEqual(format_datetime(t), "yesterday")

    def test_days_ago(self):
        t = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        self.assertEqual(format_datetime(t), "4d ago")

    def test_older_than_a_week(self):
        t = datetime(2023, 6, 15, tzinfo=timezone.utc).isoformat()
        self.assertEqual(format_datetime(t), "Jun 15, 2023")

    def test_naive_datetime_treated_as_utc(self):
        t = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(tzinfo=None).isoformat()
        self.assertEqual(format_datetime(t), "10m ago")

    def test_invalid_string_returned_as_is(self):
        self.assertEqual(format_datetime("not-a-date"), "not-a-date")
