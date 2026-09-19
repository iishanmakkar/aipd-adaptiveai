"""SSRF guard for server-side browsing endpoints.

Same policy as backend/app/api/url_guard.py (duplicated, not shared: these are
separate container images with no common package):
  - public http/https only (every resolved IP must be global unicast)
  - data: URLs allowed up to a size cap
  - file:// NEVER (would read the server's own filesystem)
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

DATA_URL_MAX_CHARS = 200_000


def _resolve(host: str):
    """DNS wrapper (module-level so tests can patch without network)."""
    return socket.getaddrinfo(host, None)


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return not addr.is_global


def validate_browse_url(url: str) -> str:
    """Return url if fetchable under the policy, else raise ValueError (→422)."""
    if not url or not isinstance(url, str):
        raise ValueError("url must be a non-empty string")
    if url.startswith("data:"):
        if len(url) > DATA_URL_MAX_CHARS:
            raise ValueError(f"data: URL exceeds {DATA_URL_MAX_CHARS} chars")
        return url
    if url.startswith("file://"):
        raise ValueError("file:// URLs are refused server-side (local filesystem)")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("url must be public http(s) or data:")
    try:
        infos = _resolve(parsed.hostname)
    except OSError:
        raise ValueError(f"cannot resolve host: {parsed.hostname}")
    ips = {info[4][0] for info in infos}
    if not ips or any(_ip_blocked(ip) for ip in ips):
        raise ValueError(f"host resolves to non-public address: {parsed.hostname}")
    return url
