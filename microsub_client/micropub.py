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


def query_config(endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(
            endpoint,
            headers=headers,
            params={"q": "config"},
            timeout=15,
        )
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code != 200:
        raise MicropubError(
            f"Micropub config error: {resp.status_code} {resp.text[:200]}"
        )

    return resp.json()


def upload_media(media_endpoint, token, file):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(
            media_endpoint,
            headers=headers,
            files={"file": (file.name, file, file.content_type)},
            timeout=30,
            allow_redirects=False,
        )
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code not in (201, 202):
        raise MicropubError(
            f"Media upload error: {resp.status_code} {resp.text[:200]}"
        )

    location = resp.headers.get("Location", "")
    if not location:
        raise MicropubError("Media endpoint did not return a Location header")
    return location


def create_post(endpoint, token, content, name=None, category=None,
                photo=None, location=None):
    data = {"h": "entry", "content": content}
    if name:
        data["name"] = name
    if category:
        data["category[]"] = category
    if photo:
        data["photo[]"] = photo
    if location:
        data["location"] = location
    return _post(endpoint, token, data)
