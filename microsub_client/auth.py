import hashlib
import re
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, urljoin

import mf2py
import requests
from requests.exceptions import RequestException

from django.core.cache import cache

from .outbound import (
    UnsafeOutboundURLError,
    normalize_url,
    parse_json_response,
    safe_request,
    validate_outbound_url,
)

HCARD_CACHE_TTL = 3600       # 1 hour
ENDPOINTS_CACHE_TTL = 300    # 5 minutes


def _hcard_cache_key(url: str) -> str:
    return f"hcard:{hashlib.md5(url.encode()).hexdigest()}"


def _endpoints_cache_key(url: str) -> str:
    return f"endpoints:{hashlib.md5(url.encode()).hexdigest()}"


def _fetch_hcard_uncached(url):
    """Fetch and parse h-card from a URL. Returns dict with 'name' and 'photo'."""
    url = normalize_url(url)
    try:
        resp = safe_request(
            url,
            send=requests.get,
            timeout=10,
            headers={"Accept": "text/html"},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except (RequestException, UnsafeOutboundURLError):
        return {"name": None, "photo": None}

    parsed = mf2py.parse(resp.text, url=url)
    for item in parsed.get("items", []):
        if "h-card" in item.get("type", []):
            props = item.get("properties", {})
            name = props.get("name", [None])[0]
            photo = props.get("photo", [None])[0]
            if isinstance(photo, dict):
                photo = photo.get("value")
            return {"name": name, "photo": photo}
    return {"name": None, "photo": None}


def fetch_hcard(url: str) -> dict:
    """Fetch and parse h-card from a URL. Returns dict with 'name' and 'photo'. Cached for 1 hour."""
    key = _hcard_cache_key(url)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = _fetch_hcard_uncached(url)
    cache.set(key, result, HCARD_CACHE_TTL)
    return result


def _discover_endpoints_uncached(url):
    """Fetch a user's URL and discover IndieAuth and Microsub endpoints.

    Checks both HTML <link> tags and HTTP Link headers.
    Returns dict with keys: authorization_endpoint, token_endpoint, microsub.
    """
    url = normalize_url(url, trailing_slash=True)

    endpoints = {
        "authorization_endpoint": None,
        "token_endpoint": None,
        "microsub": None,
        "micropub": None,
    }

    try:
        resp = safe_request(
            url,
            send=requests.get,
            timeout=10,
            headers={"Accept": "text/html"},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except UnsafeOutboundURLError as exc:
        raise ValueError(str(exc)) from exc
    except RequestException as exc:
        raise ValueError(f"Could not fetch {url}: {exc}") from exc

    def _safe_endpoint(href):
        candidate = urljoin(url, href)
        try:
            return validate_outbound_url(candidate)
        except UnsafeOutboundURLError:
            return None

    # Check HTTP Link headers
    link_header = resp.headers.get("Link", "")
    for part in link_header.split(","):
        for rel in endpoints:
            pattern = rf'<([^>]+)>;\s*rel="{re.escape(rel)}"'
            match = re.search(pattern, part)
            if match:
                endpoints[rel] = _safe_endpoint(match.group(1))

    # Check HTML <link> tags (overrides headers if both present)
    html = resp.text
    for rel in endpoints:
        pattern = rf'<link[^>]+rel="{re.escape(rel)}"[^>]+href="([^"]+)"'
        match = re.search(pattern, html)
        if match:
            endpoints[rel] = _safe_endpoint(match.group(1))
        # Also try reversed attribute order
        pattern = rf'<link[^>]+href="([^"]+)"[^>]+rel="{re.escape(rel)}"'
        match = re.search(pattern, html)
        if match:
            endpoints[rel] = _safe_endpoint(match.group(1))

    return endpoints


def discover_endpoints(url: str) -> dict:
    """Fetch a user's URL and discover IndieAuth and Microsub endpoints. Cached for 5 minutes."""
    key = _endpoints_cache_key(url)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = _discover_endpoints_uncached(url)
    cache.set(key, result, ENDPOINTS_CACHE_TTL)
    return result


def generate_pkce_pair():
    """Generate a PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorization_url(
    auth_endpoint, me, redirect_uri, state, client_id, code_challenge
):
    """Build the IndieAuth authorization URL with PKCE."""
    params = {
        "me": me,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "read follow channels create",
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return auth_endpoint + "?" + urlencode(params)


def exchange_code_for_token(token_endpoint, code, redirect_uri, client_id, code_verifier):
    """Exchange an authorization code for an access token.

    Returns dict with 'access_token' and 'me' on success.
    Raises ValueError on failure.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    try:
        resp = safe_request(
            token_endpoint,
            send=requests.post,
            data=data,
            headers={"Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
        resp.raise_for_status()
    except UnsafeOutboundURLError as exc:
        raise ValueError(f"Token exchange failed: {exc}") from exc
    except RequestException as exc:
        raise ValueError(f"Token exchange failed: {exc}") from exc

    result = parse_json_response(resp, ValueError, "Token exchange failed")
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise ValueError(f"Token exchange failed: {error}")

    return result
