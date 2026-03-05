import pytest
from django.core.cache import cache


@pytest.mark.django_db
def test_cache_set_and_get():
    cache.set("smoke_test", "hello", 60)
    assert cache.get("smoke_test") == "hello"


@pytest.mark.django_db
def test_cache_delete():
    cache.set("del_test", "value", 60)
    cache.delete("del_test")
    assert cache.get("del_test") is None
