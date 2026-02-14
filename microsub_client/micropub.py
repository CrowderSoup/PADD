import requests
from requests.exceptions import RequestException


class MicropubError(Exception):
    pass


class AuthenticationError(MicropubError):
    pass


def _post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(
            endpoint,
            headers=headers,
            data=data,
            timeout=15,
            allow_redirects=False,
        )
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code not in (201, 202):
        raise MicropubError(
            f"Micropub error: {resp.status_code} {resp.text[:200]}"
        )

    return resp.headers.get("Location", "")


def like(endpoint, token, url):
    return _post(endpoint, token, {"h": "entry", "like-of": url})


def reply(endpoint, token, url, content):
    return _post(
        endpoint, token, {"h": "entry", "in-reply-to": url, "content": content}
    )


def repost(endpoint, token, url):
    return _post(endpoint, token, {"h": "entry", "repost-of": url})
