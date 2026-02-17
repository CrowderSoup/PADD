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


def mark_read(endpoint, token, channel_uid, entry_ids):
    if isinstance(entry_ids, str):
        entry_ids = [entry_ids]
    data = [
        ("action", "timeline"),
        ("method", "mark_read"),
        ("channel", channel_uid),
    ] + [("entry[]", eid) for eid in entry_ids]
    return _request("POST", endpoint, token, data=data)


def mark_unread(endpoint, token, channel_uid, entry_id):
    data = {
        "action": "timeline",
        "method": "mark_unread",
        "channel": channel_uid,
        "entry[]": entry_id,
    }
    return _request("POST", endpoint, token, data=data)


def remove_entry(endpoint, token, channel_uid, entry_id):
    data = {
        "action": "timeline",
        "method": "remove",
        "channel": channel_uid,
        "entry[]": entry_id,
    }
    return _request("POST", endpoint, token, data=data)


# --- Channel Management ---


def create_channel(endpoint, token, name):
    data = {
        "action": "channels",
        "name": name,
    }
    return _request("POST", endpoint, token, data=data)


def update_channel(endpoint, token, channel_uid, name):
    data = {
        "action": "channels",
        "channel": channel_uid,
        "name": name,
    }
    return _request("POST", endpoint, token, data=data)


def delete_channel(endpoint, token, channel_uid):
    data = {
        "action": "channels",
        "channel": channel_uid,
        "method": "delete",
    }
    return _request("POST", endpoint, token, data=data)


def order_channels(endpoint, token, channel_uids):
    data = {
        "action": "channels",
        "method": "order",
    }
    # requests library sends multiple values for the same key when given a list
    data_list = list(data.items()) + [("channels[]", uid) for uid in channel_uids]
    return _request("POST", endpoint, token, data=data_list)


# --- Feed Management ---


def search_feeds(endpoint, token, query):
    return _request("POST", endpoint, token, data={
        "action": "search",
        "query": query,
    })


def preview_feed(endpoint, token, url):
    return _request("GET", endpoint, token, params={
        "action": "preview",
        "url": url,
    })


def get_follows(endpoint, token, channel_uid):
    return _request("GET", endpoint, token, params={
        "action": "follow",
        "channel": channel_uid,
    })


def follow_feed(endpoint, token, channel_uid, url):
    return _request("POST", endpoint, token, data={
        "action": "follow",
        "channel": channel_uid,
        "url": url,
    })


def unfollow_feed(endpoint, token, channel_uid, url):
    return _request("POST", endpoint, token, data={
        "action": "unfollow",
        "channel": channel_uid,
        "url": url,
    })
