"""Guard tests for this image's copy of the SSRF policy.

browser-agent/app/tools/url_guard.py is deliberately duplicated from
backend/app/api/url_guard.py (separate images, no shared package), so the
duplicate is tested here rather than only on the backend side.
"""
import pytest

import app.tools.url_guard as guard
from app.tools.url_guard import validate_browse_url


def fake_resolve(ip):
    def _resolve(host):
        return [(2, 1, 6, "", (ip, 0))]
    return _resolve


def test_file_and_internal_refused_by_default(monkeypatch):
    monkeypatch.delenv(guard.LOCAL_TARGETS_ENV, raising=False)
    with pytest.raises(ValueError, match="filesystem"):
        validate_browse_url("file:///etc/passwd")
    for ip in ["127.0.0.1", "169.254.169.254", "::1"]:
        monkeypatch.setattr(guard, "_resolve", fake_resolve(ip))
        with pytest.raises(ValueError, match="non-public"):
            validate_browse_url("http://internal-host.test/page")
    monkeypatch.setattr(guard, "_resolve", fake_resolve("8.8.8.8"))
    assert validate_browse_url("https://example.com/") == "https://example.com/"


def test_opt_in_allows_internal_never_metadata(monkeypatch):
    monkeypatch.setenv(guard.LOCAL_TARGETS_ENV, "1")
    monkeypatch.setattr(guard, "_resolve", fake_resolve("172.18.0.5"))
    assert validate_browse_url("http://demo-forms:8080/book-tickets.html")
    monkeypatch.setattr(guard, "_resolve", fake_resolve("169.254.169.254"))
    with pytest.raises(ValueError):
        validate_browse_url("http://metadata.example/latest/meta-data")
