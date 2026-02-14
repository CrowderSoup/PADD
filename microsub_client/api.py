import requests
from requests.exceptions import RequestException


class MicrosubError(Exception):
    pass


class AuthenticationError(MicrosubError):
    pass


def _request(method, endpoint, token, params=None, data=None):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.request(
            method,
            endpoint,
            headers=headers,
            params=params,
            data=data,
            timeout=15,
        )
    except RequestException as exc:
        raise MicrosubError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise AuthenticationError("Access token is invalid or expired")
    if not resp.ok:
        raise MicrosubError(f"Microsub API error: {resp.status_code}")

    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def get_channels(endpoint, token):
    result = _request("GET", endpoint, token, params={"action": "channels"})
    return result.get("channels", [])


def get_timeline(endpoint, token, channel_uid, after=None, is_read=None):
    params = {"action": "timeline", "channel": channel_uid}
    if after:
        params["after"] = after
    if is_read is not None:
        params["is_read"] = "true" if is_read else "false"
    return _request("GET", endpoint, token, params=params)


def mark_read(endpoint, token, channel_uid, entry_id):
    data = {
        "action": "timeline",
        "method": "mark_read",
        "channel": channel_uid,
        "entry[]": entry_id,
    }
    return _request("POST", endpoint, token, data=data)
