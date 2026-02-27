import requests
from requests.exceptions import RequestException


class MicrosubError(Exception):
    pass


class AuthenticationError(MicrosubError):
    pass


def _request(method, endpoint, token, params=None, data=None):
    """Make an authenticated request to a Microsub endpoint.

    Args:
        method: HTTP method string ("GET" or "POST").
        endpoint: The Microsub endpoint URL.
        token: Bearer access token.
        params: Optional dict of query parameters.
        data: Optional form data (dict or list of tuples for multi-value fields).

    Returns:
        dict: Parsed JSON response body, or {} for 204 No Content.

    Raises:
        AuthenticationError: If the server returns 401.
        MicrosubError: On network errors or non-2xx responses.
    """
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
    """Fetch all channels from the Microsub server. Returns a list of channel dicts."""
    result = _request("GET", endpoint, token, params={"action": "channels"})
    return result.get("channels", [])


def get_timeline(endpoint, token, channel_uid, after=None, is_read=None):
    """Fetch a page of timeline entries for a channel.

    Args:
        after: Pagination cursor returned by a previous response.
        is_read: If True/False, filter to read/unread entries. None returns all.

    Returns:
        dict: Response body with "items" list and optional "paging" dict.
    """
    params = {"action": "timeline", "channel": channel_uid}
    if after:
        params["after"] = after
    if is_read is not None:
        params["is_read"] = "true" if is_read else "false"
    return _request("GET", endpoint, token, params=params)


def mark_read(endpoint, token, channel_uid, entry_ids):
    """Mark one or more entries as read. Accepts a single ID string or a list."""
    if isinstance(entry_ids, str):
        entry_ids = [entry_ids]
    data = [
        ("action", "timeline"),
        ("method", "mark_read"),
        ("channel", channel_uid),
    ] + [("entry[]", eid) for eid in entry_ids]
    return _request("POST", endpoint, token, data=data)


def mark_channel_read(endpoint, token, channel_uid):
    """Mark all unread entries in a channel as read.

    Some Microsub servers reject channel-level mark_read calls without entry IDs.
    To be compatible, repeatedly fetch unread entries and mark each batch by ID.
    """
    marked_count = 0
    previous_ids = None

    def _entry_id_for_mark_read(item):
        for key in ("_id", "id", "entry_id", "url"):
            value = item.get(key)
            if isinstance(value, list):
                value = value[0] if value else ""
            if isinstance(value, str) and value:
                return value
        return ""

    while True:
        timeline = get_timeline(endpoint, token, channel_uid, is_read=False)
        items = timeline.get("items", [])
        entry_ids = [eid for eid in (_entry_id_for_mark_read(item) for item in items) if eid]

        if not entry_ids:
            break

        # Guard against an endless loop if the server returns the same unread
        # items after a successful response.
        if entry_ids == previous_ids:
            raise MicrosubError("Unable to mark channel read; unread entries did not change")

        mark_read(endpoint, token, channel_uid, entry_ids)
        marked_count += len(entry_ids)
        previous_ids = entry_ids

    return {"marked": marked_count}


def mark_unread(endpoint, token, channel_uid, entry_id):
    """Mark a single entry as unread."""
    data = {
        "action": "timeline",
        "method": "mark_unread",
        "channel": channel_uid,
        "entry[]": entry_id,
    }
    return _request("POST", endpoint, token, data=data)


def remove_entry(endpoint, token, channel_uid, entry_id):
    """Remove an entry from a channel's timeline."""
    data = {
        "action": "timeline",
        "method": "remove",
        "channel": channel_uid,
        "entry[]": entry_id,
    }
    return _request("POST", endpoint, token, data=data)


# --- Channel Management ---


def create_channel(endpoint, token, name):
    """Create a new channel with the given name."""
    data = {
        "action": "channels",
        "name": name,
    }
    return _request("POST", endpoint, token, data=data)


def update_channel(endpoint, token, channel_uid, name):
    """Rename an existing channel."""
    data = {
        "action": "channels",
        "channel": channel_uid,
        "name": name,
    }
    return _request("POST", endpoint, token, data=data)


def delete_channel(endpoint, token, channel_uid):
    """Delete a channel."""
    data = {
        "action": "channels",
        "channel": channel_uid,
        "method": "delete",
    }
    return _request("POST", endpoint, token, data=data)


def order_channels(endpoint, token, channel_uids):
    """Reorder channels to match the given list of UIDs."""
    data = {
        "action": "channels",
        "method": "order",
    }
    # requests library sends multiple values for the same key when given a list
    data_list = list(data.items()) + [("channels[]", uid) for uid in channel_uids]
    return _request("POST", endpoint, token, data=data_list)


# --- Feed Management ---


def search_feeds(endpoint, token, query):
    """Search for feeds matching a query string. Returns a result dict with "results" list."""
    return _request("POST", endpoint, token, data={
        "action": "search",
        "query": query,
    })


def preview_feed(endpoint, token, url):
    """Fetch a preview of a feed URL. Returns a result dict with "items" list."""
    return _request("GET", endpoint, token, params={
        "action": "preview",
        "url": url,
    })


def get_follows(endpoint, token, channel_uid):
    """List feeds the user follows in a channel. Returns a result dict with "items" list."""
    return _request("GET", endpoint, token, params={
        "action": "follow",
        "channel": channel_uid,
    })


def follow_feed(endpoint, token, channel_uid, url):
    """Subscribe to a feed URL in the given channel."""
    return _request("POST", endpoint, token, data={
        "action": "follow",
        "channel": channel_uid,
        "url": url,
    })


def unfollow_feed(endpoint, token, channel_uid, url):
    """Unsubscribe from a feed URL in the given channel."""
    return _request("POST", endpoint, token, data={
        "action": "unfollow",
        "channel": channel_uid,
        "url": url,
    })


# --- Mute / Block ---


def mute_user(endpoint, token, url, channel=None):
    """Mute an author. If channel is provided, mute is channel-specific."""
    data = {"action": "mute", "url": url}
    if channel:
        data["channel"] = channel
    return _request("POST", endpoint, token, data=data)


def unmute_user(endpoint, token, url, channel=None):
    """Unmute a previously muted author."""
    data = {"action": "unmute", "url": url}
    if channel:
        data["channel"] = channel
    return _request("POST", endpoint, token, data=data)


def block_user(endpoint, token, url):
    """Block an author globally."""
    return _request("POST", endpoint, token, data={"action": "block", "url": url})
