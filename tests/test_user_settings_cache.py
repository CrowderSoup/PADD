import pytest
from unittest.mock import patch
from django.core.cache import cache
from django.test import RequestFactory

from microsub_client.models import UserSettings
from microsub_client.views import _get_user_settings, _user_settings_cache_key


@pytest.mark.django_db
def test_user_settings_cache_key_is_consistent():
    k1 = _user_settings_cache_key("https://example.com/")
    k2 = _user_settings_cache_key("https://example.com/")
    assert k1 == k2


@pytest.mark.django_db
def test_user_settings_cache_key_differs_per_user():
    k_alice = _user_settings_cache_key("https://alice.example.com/")
    k_bob = _user_settings_cache_key("https://bob.example.com/")
    assert k_alice != k_bob


@pytest.mark.django_db
def test_get_user_settings_caches_result():
    """Second call should not hit the DB."""
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {"user_url": "https://example.com/"}

    # First call: hits DB, populates cache
    settings1 = _get_user_settings(request)

    # Verify cache is populated
    key = _user_settings_cache_key("https://example.com/")
    assert cache.get(key) is not None

    # Second call: should use cache, not DB
    with patch("microsub_client.views.UserSettings.objects.get_or_create") as mock_db:
        settings2 = _get_user_settings(request)
        mock_db.assert_not_called()

    assert settings1.user_url == settings2.user_url


@pytest.mark.django_db
def test_get_user_settings_raises_on_missing_user_url():
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {}

    with pytest.raises(ValueError, match="Missing user_url"):
        _get_user_settings(request)
