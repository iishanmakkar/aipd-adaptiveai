"""SSRF guard for server-side browsing endpoints.

A Playwright service reachable over a network must never fetch arbitrary
internal URLs. Policy:
  - public http/https only (after DNS resolution - every resolved IP must be
    global unicast; this blocks 10/8, 172.16/12, 192.168/16, 127/8,
    169.254/16 incl. cloud metadata, ::1, multicast/reserved)
  - data: URLs allowed (self-contained pages, no network fetch) up to a size cap
  - file:// NEVER (would read the server's own filesystem)
  - with ADAPTIVEAI_ALLOW_LOCAL_TARGETS=1, loopback/RFC1918 http(s) hosts are
    allowed too. That is what makes the ticket-booking demo, a self-hosted
    intranet form, and a local replay/heal test possible. It is OFF by default,
    the prod overlay pins it to 0, and cloud metadata (169.254/16) stays
    refused even when it is on.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

DATA_URL_MAX_CHARS = 200_000
LOCAL_TARGETS_ENV = "ADAPTIVEAI_ALLOW_LOCAL_TARGETS"


def _resolve(host: str):
    """DNS wrapper (module-level so tests can patch without network)."""
    return socket.getaddrinfo(host, None)


def _local_targets_allowed() -> bool:
    return os.environ.get(LOCAL_TARGETS_ENV, "").strip() == "1"


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    # Unwrap mapped/compatible forms attackers use to dodge the check.
    if getattr(addr, "ipv4_mapped", None) is not None:
        addr = addr.ipv4_mapped
    elif getattr(addr, "sixtofour", None) is not None:
        try:
            addr = addr.sixtofour
        except Exception:
            return True
    try:
        if addr in ipaddress.ip_network("2002::/16") or addr in ipaddress.ip_network("2001::/32") or addr in ipaddress.ip_network("64:ff9b::/96"):
            return True
    except Exception:
        pass
    # Checked before the reserved test: Python flags ::1 as reserved as well as
    # loopback, and an opt-in that refuses IPv6 loopback while allowing 127.0.0.1
    # would be an inconsistency, not a safety gain.
    if addr.is_loopback:
        return not _local_targets_allowed()
    if addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        # Cloud metadata (169.254.169.254) and friends: never, under any setting.
        return True
    if addr.is_global:
        return False
    # ponytail: explicit allowlist when local opt-in, deny rest (CGNAT/TEST-NET/0/8)
    if _local_targets_allowed():
        try:
            return not (addr.is_loopback or addr.is_private)
        except Exception:
            return True
    return True


def validate_browse_url(url: str) -> str:
    """Return url if fetchable under the policy, else raise ValueError (->422)."""
    if not url or not isinstance(url, str):
        raise ValueError("url must be a non-empty string")
    if url.startswith("data:"):
        if len(url) > DATA_URL_MAX_CHARS:
            raise ValueError(f"data: URL exceeds {DATA_URL_MAX_CHARS} chars")
        return url
    if url.startswith("file://"):
        raise ValueError("file:// URLs are refused server-side (local filesystem)")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "ws", "wss") or not parsed.hostname:
        raise ValueError("url must be public http(s)/ws(s) or data:")
    try:
        infos = _resolve(parsed.hostname)
    except OSError:
        if _local_targets_allowed() and parsed.hostname == "localhost":
            # With local targets on, localhost must work even on a host whose
            # resolver has no answer for it (some containers have no ::1 entry).
            infos = [(2, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
        else:
            raise ValueError(f"cannot resolve host: {parsed.hostname}")
    ips = {info[4][0] for info in infos}
    if not ips or any(_ip_blocked(ip) for ip in ips):
        refused = "non-public" if not _local_targets_allowed() else "internal (link-local/reserved)"
        raise ValueError(f"host resolves to a {refused} address: {parsed.hostname}")
    return url
