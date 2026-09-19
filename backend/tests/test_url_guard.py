"""SSRF guard tests (offline: DNS is patched, no network).

Proves the browsing endpoints refuse server-filesystem reads, internal
addresses, and cloud-metadata IPs while letting public URLs and small
self-contained data: pages through.
"""
import pytest

import app.api.url_guard as guard
from app.api.url_guard import validate_browse_url


def fake_resolve(ip):
    def _resolve(host):
        return [(2, 1, 6, "", (ip, 0))]
    return _resolve


def test_file_url_refused():
    with pytest.raises(ValueError, match="filesystem"):
        validate_browse_url("file:///etc/passwd")


def test_ftp_and_empty_refused():
    with pytest.raises(ValueError):
        validate_browse_url("ftp://example.com/x")
    with pytest.raises(ValueError):
        validate_browse_url("")


def test_loopback_private_linklocal_metadata_refused(monkeypatch):
    for ip in ["127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1",
               "169.254.169.254", "0.0.0.0", "::1"]:
        monkeypatch.setattr(guard, "_resolve", fake_resolve(ip))
        with pytest.raises(ValueError, match="non-public"):
            validate_browse_url(f"http://internal-{ip}.example/{ip}")


def test_public_ip_allowed(monkeypatch):
    monkeypatch.setattr(guard, "_resolve", fake_resolve("8.8.8.8"))
    assert validate_browse_url("https://example.com/page") == "https://example.com/page"


def test_unresolvable_host_refused(monkeypatch):
    def boom(host):
        raise OSError("nope")
    monkeypatch.setattr(guard, "_resolve", boom)
    with pytest.raises(ValueError, match="cannot resolve"):
        validate_browse_url("https://does-not-exist.invalid/")


def test_data_url_allowed_and_capped():
    assert validate_browse_url("data:text/html,<form></form>").startswith("data:")
    with pytest.raises(ValueError, match="exceeds"):
        validate_browse_url("data:text/html," + "x" * (guard.DATA_URL_MAX_CHARS + 1))


def test_form_fill_route_uses_guard(client):
    # file:// previously passed validation; now it must 422, not reach Chromium.
    r = client.post("/api/form-fill",
                    json={"url": "file:///etc/passwd", "values": {"a": "b"}})
    assert r.status_code == 422
    assert "filesystem" in r.json()["detail"]
