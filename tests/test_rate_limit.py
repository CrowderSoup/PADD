import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_login_rate_limit_blocks_after_threshold():
    """After 10 POST requests in a short window, the 11th gets an error response."""
    client = Client()
    url = reverse("login")

    # Make 10 requests (at the limit)
    for _ in range(10):
        response = client.post(url, {"url": "https://example.com/"})
        # Each may fail (no real endpoint) but should not be rate-limited
        assert b"Too many login attempts" not in response.content

    # 11th request should be rate-limited
    response = client.post(url, {"url": "https://example.com/"})
    assert b"Too many login attempts" in response.content


@pytest.mark.django_db
def test_login_get_is_not_rate_limited():
    """GET requests to login are never rate-limited."""
    client = Client()
    url = reverse("login")
    for _ in range(20):
        response = client.get(url)
        assert response.status_code == 200
