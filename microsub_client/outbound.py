import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from requests.models import PreparedRequest


class UnsafeOutboundURLError(ValueError):
    """Raised when PADD is asked to fetch an unsafe outbound URL."""


_ALLOWED_SCHEMES = {"http", "https"}
_DOCUMENTATION_HOSTS = {
    "example",
    "example.com",
    "example.net",
    "example.org",
    "test",
    "invalid",
}
_DOCUMENTATION_SUFFIXES = (
    ".example",
    ".example.com",
    ".example.net",
    ".example.org",
    ".test",
    ".invalid",
)
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


def normalize_url(url: str, default_scheme: str = "https", trailing_slash: bool = False) -> str:
    normalized = (url or "").strip()
    if not normalized:
        raise UnsafeOutboundURLError("Please enter a URL.")
    if "://" not in normalized:
        normalized = f"{default_scheme}://{normalized}"
    if trailing_slash and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _is_documentation_hostname(hostname: str) -> bool:
    host = hostname.lower()
    return host in _DOCUMENTATION_HOSTS or host.endswith(_DOCUMENTATION_SUFFIXES)


def _is_safe_ip(ip_text: str) -> bool:
    return ipaddress.ip_address(ip_text).is_global


def validate_outbound_url(url: str, allowed_schemes: set[str] | None = None) -> str:
    allowed_schemes = allowed_schemes or _ALLOWED_SCHEMES
    parsed = urlparse(url)

    if parsed.scheme not in allowed_schemes:
        raise UnsafeOutboundURLError("Only http:// and https:// URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeOutboundURLError("URL must include a hostname.")
    if parsed.username or parsed.password:
        raise UnsafeOutboundURLError("Credentials in URLs are not allowed.")

    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeOutboundURLError("Local addresses are not allowed.")

    if _is_documentation_hostname(host):
        return url

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            resolved = {
                result[4][0]
                for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            }
        except socket.gaierror as exc:
            raise UnsafeOutboundURLError(f"Could not resolve {host}.") from exc

        if not resolved:
            raise UnsafeOutboundURLError(f"Could not resolve {host}.")
        if any(not _is_safe_ip(ip_text) for ip_text in resolved):
            raise UnsafeOutboundURLError("Private or special-use network addresses are not allowed.")
        return url

    if not _is_safe_ip(str(ip)):
        raise UnsafeOutboundURLError("Private or special-use network addresses are not allowed.")
    return url


def prepare_url(url: str, params=None) -> str:
    if not params:
        return url

    prepared = PreparedRequest()
    prepared.prepare_url(url, params)
    return prepared.url


def safe_request(
    url: str,
    *,
    send,
    params=None,
    allow_redirects: bool,
    max_redirects: int = 3,
    **kwargs,
):
    current_url = validate_outbound_url(prepare_url(url, params))
    redirects_followed = 0

    while True:
        response = send(current_url, allow_redirects=False, **kwargs)
        headers = getattr(response, "headers", {}) or {}
        location = headers.get("Location") if hasattr(headers, "get") else None

        if response.status_code in _REDIRECT_STATUS_CODES and location:
            if not allow_redirects:
                raise UnsafeOutboundURLError("Redirects are not allowed for this request.")
            redirects_followed += 1
            if redirects_followed > max_redirects:
                raise UnsafeOutboundURLError("Too many redirects while fetching remote content.")
            current_url = validate_outbound_url(urljoin(current_url, location))
            continue

        return response


def parse_json_response(response, error_cls, message: str):
    try:
        return response.json()
    except ValueError as exc:
        raise error_cls(f"{message}: invalid JSON response") from exc
