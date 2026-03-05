import pytest
from django.core.cache import cache
from django.test import RequestFactory

from microsub_client.context_processors import broadcasts, _broadcasts_cache_key
from microsub_client.models import Broadcast, DismissedBroadcast


@pytest.mark.django_db
def test_broadcasts_cache_key_consistent():
    k1 = _broadcasts_cache_key("https://example.com/")
    k2 = _broadcasts_cache_key("https://example.com/")
    assert k1 == k2


@pytest.mark.django_db
def test_broadcasts_context_caches_result():
    Broadcast.objects.create(message="Hello world", is_active=True)

    factory = RequestFactory()
    request = factory.get("/")
    request.session = {
        "access_token": "tok",
        "user_url": "https://example.com/",
    }

    # First call: populates cache
    result1 = broadcasts(request)
    key = _broadcasts_cache_key("https://example.com/")
    assert cache.get(key) is not None

    # Delete DB records — second call must still return cached data
    Broadcast.objects.all().delete()
    result2 = broadcasts(request)
    assert len(result2["active_broadcasts"]) == 1


@pytest.mark.django_db
def test_broadcasts_cache_empty_when_no_token():
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {}
    result = broadcasts(request)
    assert result["active_broadcasts"] == []
    assert result["is_admin"] is False


@pytest.mark.django_db
def test_broadcasts_cache_invalidated_on_dismiss():
    """After dismiss, cache is cleared so next call re-fetches from DB."""
    broadcast = Broadcast.objects.create(message="Hello", is_active=True)
    user_url = "https://example.com/"

    factory = RequestFactory()
    request = factory.get("/")
    request.session = {"access_token": "tok", "user_url": user_url}

    # Populate cache
    broadcasts(request)
    key = _broadcasts_cache_key(user_url)
    assert cache.get(key) is not None

    # Simulate dismiss
    cache.delete(_broadcasts_cache_key(user_url))

    # Cache is now empty
    assert cache.get(key) is None
