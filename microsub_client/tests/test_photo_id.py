from django.test import SimpleTestCase

from microsub_client.photo_id import photo_url_hash


class PhotoUrlHashTests(SimpleTestCase):
    def test_deterministic_for_same_url(self):
        url = "https://media.example.com/uploads/abc123.jpg"
        self.assertEqual(photo_url_hash(url), photo_url_hash(url))

    def test_differs_for_different_urls(self):
        a = photo_url_hash("https://media.example.com/uploads/abc123.jpg")
        b = photo_url_hash("https://media.example.com/uploads/xyz789.jpg")
        self.assertNotEqual(a, b)

    def test_matches_known_fnv1a_vector(self):
        # Cross-checked against the JS implementation in static/js/new-post.js
        # (photoUrlHash) — the two must stay in sync.
        self.assertEqual(
            photo_url_hash("https://media.example.com/uploads/abc123.jpg"),
            "9c872dcc",
        )
        self.assertEqual(
            photo_url_hash("https://media.example.com/uploads/xyz789.jpg"),
            "9ad584d3",
        )

    def test_returns_eight_hex_chars(self):
        h = photo_url_hash("https://example.com/x.jpg")
        self.assertEqual(len(h), 8)
        int(h, 16)  # raises if not valid hex
