import pytest
from unittest.mock import patch
from django.core.cache import cache

from microsub_client.auth import fetch_hcard, discover_endpoints
from microsub_client.views import _get_channels_cached, _channels_cache_key


@pytest.mark.django_db
def test_fetch_hcard_caches_result():
    """Second call should not make an HTTP request."""
    mock_result = {"name": "Alice", "photo": "https://example.com/photo.jpg"}

    with patch("microsub_client.auth._fetch_hcard_uncached", return_value=mock_result) as mock_fn:
        result1 = fetch_hcard("https://alice.example.com/")
        result2 = fetch_hcard("https://alice.example.com/")

    assert mock_fn.call_count == 1
    assert result1 == mock_result
    assert result2 == mock_result


@pytest.mark.django_db
def test_fetch_hcard_different_urls_have_different_cache():
    """Different URLs get independent cache entries."""
    with patch("microsub_client.auth._fetch_hcard_uncached") as mock_fn:
        mock_fn.return_value = {"name": "Alice", "photo": None}
        fetch_hcard("https://alice.example.com/")

        mock_fn.return_value = {"name": "Bob", "photo": None}
        result = fetch_hcard("https://bob.example.com/")

    assert result["name"] == "Bob"


@pytest.mark.django_db
def test_discover_endpoints_caches_result():
    """Second call should not make an HTTP request."""
    mock_endpoints = {
        "authorization_endpoint": "https://example.com/auth",
        "token_endpoint": "https://example.com/token",
        "microsub": "https://example.com/microsub",
        "micropub": None,
    }

    with patch("microsub_client.auth._discover_endpoints_uncached", return_value=mock_endpoints) as mock_fn:
        result1 = discover_endpoints("https://example.com/")
        result2 = discover_endpoints("https://example.com/")

    assert mock_fn.call_count == 1
    assert result1 == mock_endpoints


@pytest.mark.django_db
def test_get_channels_cached_avoids_repeat_call():
    """Second call to _get_channels_cached returns cached value without hitting API."""
    mock_channels = [{"uid": "home", "name": "Home"}]

    with patch("microsub_client.api.get_channels", return_value=mock_channels) as mock_fn:
        ch1 = _get_channels_cached("https://microsub.example.com/", "token-abc")
        ch2 = _get_channels_cached("https://microsub.example.com/", "token-abc")

    assert mock_fn.call_count == 1
    assert ch1 == mock_channels
    assert ch2 == mock_channels


@pytest.mark.django_db
def test_channels_cache_key_differs_per_token():
    """Different tokens produce different cache keys."""
    k1 = _channels_cache_key("https://microsub.example.com/", "token-1")
    k2 = _channels_cache_key("https://microsub.example.com/", "token-2")
    assert k1 != k2
