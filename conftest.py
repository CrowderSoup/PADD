import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    yield
    cache.clear()
