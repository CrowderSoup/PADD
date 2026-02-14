# WhiteNoise's manifest storage fails without collectstatic; use simple backend in tests.
SIMPLE_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


def auth_session():
    """Return a session dict for an authenticated user."""
    return {
        "access_token": "test-token",
        "microsub_endpoint": "https://microsub.example/",
        "micropub_endpoint": "https://micropub.example/",
        "user_url": "https://me.example/",
    }
