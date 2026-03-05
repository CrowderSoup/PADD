import fakeredis
import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def use_fakeredis(settings):
    """Replace the Redis cache backend with fakeredis for all tests."""
    server = fakeredis.FakeServer()
    settings.CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/1",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "REDIS_CLIENT_CLASS": "fakeredis.FakeRedis",
                "REDIS_CLIENT_KWARGS": {"server": server},
            },
            "KEY_PREFIX": "padd",
        }
    }
    yield
    cache.clear()
