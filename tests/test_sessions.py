import pytest
from django.test import Client


@pytest.mark.django_db
def test_session_data_persists_across_requests():
    """Session data written in one request is readable in the next."""
    client = Client()
    session = client.session
    session["access_token"] = "test-token-abc"
    session.save()

    assert client.session.get("access_token") == "test-token-abc"


@pytest.mark.django_db
def test_session_flush_clears_data():
    client = Client()
    session = client.session
    session["access_token"] = "test-token-abc"
    session["user_url"] = "https://example.com/"
    session.save()

    session = client.session
    session.flush()

    assert client.session.get("access_token") is None
    assert client.session.get("user_url") is None
