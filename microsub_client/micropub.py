import requests
from requests.exceptions import RequestException

from .outbound import UnsafeOutboundURLError, parse_json_response, safe_request


class MicropubError(Exception):
    pass


class AuthenticationError(MicropubError):
    pass


def _post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = safe_request(
            endpoint,
            send=requests.post,
            headers=headers,
            data=data,
            timeout=15,
            allow_redirects=False,
        )
    except UnsafeOutboundURLError as exc:
        raise MicropubError(f"Network error: {exc}") from exc
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code not in (201, 202):
        raise MicropubError(
            f"Micropub error: {resp.status_code} {resp.text[:200]}"
        )

    return resp.headers.get("Location", "")


def _post_json(endpoint, token, payload):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = safe_request(
            endpoint,
            send=requests.post,
            headers=headers,
            json=payload,
            timeout=15,
            allow_redirects=False,
        )
    except UnsafeOutboundURLError as exc:
        raise MicropubError(f"Network error: {exc}") from exc
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code not in (200, 201, 202, 204):
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
        resp = safe_request(
            endpoint,
            send=requests.get,
            headers=headers,
            params={"q": "config"},
            timeout=15,
            allow_redirects=True,
        )
    except UnsafeOutboundURLError as exc:
        raise MicropubError(f"Network error: {exc}") from exc
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code != 200:
        raise MicropubError(
            f"Micropub config error: {resp.status_code} {resp.text[:200]}"
        )

    return parse_json_response(resp, MicropubError, "Micropub config error")


def fetch_source(endpoint, token, url, properties=None):
    headers = {"Authorization": f"Bearer {token}"}
    params = [("q", "source"), ("url", url)]
    params.extend(("properties[]", prop) for prop in (properties or []))
    try:
        resp = safe_request(
            endpoint,
            send=requests.get,
            headers=headers,
            params=params,
            timeout=15,
            allow_redirects=True,
        )
    except UnsafeOutboundURLError as exc:
        raise MicropubError(f"Network error: {exc}") from exc
    except RequestException as exc:
        raise MicropubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if resp.status_code != 200:
        raise MicropubError(
            f"Micropub source error: {resp.status_code} {resp.text[:200]}"
        )

    result = parse_json_response(resp, MicropubError, "Micropub source error")
    return result.get("properties", result)


def upload_media(media_endpoint, token, file):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = safe_request(
            media_endpoint,
            send=requests.post,
            headers=headers,
            files={"file": (file.name, file, file.content_type)},
            timeout=30,
            allow_redirects=False,
        )
    except UnsafeOutboundURLError as exc:
        raise MicropubError(f"Network error: {exc}") from exc
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
                photo=None, location=None, syndicate_to=None):
    data = [("h", "entry"), ("content", content)]
    if name:
        data.append(("name", name))
    if category:
        data.extend([("category[]", t) for t in category])
    if photo:
        data.extend([("photo[]", p) for p in photo])
    if location:
        data.append(("location", location))
    if syndicate_to:
        data.extend([("syndicate-to[]", uid) for uid in syndicate_to])
    return _post(endpoint, token, data)


def update_post(endpoint, token, url, replace=None, add=None, delete=None):
    payload = {"action": "update", "url": url}
    if replace:
        payload["replace"] = replace
    if add:
        payload["add"] = add
    if delete:
        payload["delete"] = delete
    return _post_json(endpoint, token, payload)
