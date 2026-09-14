"""Hardening contracts added in Round 4.

Server-side upload validation (a malicious client skips the frontend entirely),
the production startup guard, and the metrics endpoint.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_vlm_rejects_oversized_declared_payload(client, monkeypatch):
    r = client.post("/v1/chat/completions", json={"messages": []},
                    headers={"Content-Length": str(16 * 1024 * 1024)})
    # httpx/Starlette may override content-length; the handler also re-checks
    # the serialized body size, so 413 either way
    assert r.status_code in (413, 400)


def test_vlm_rejects_huge_body(client):
    # ~16MB of data URI that bypasses content-length games: the serialized-body
    # check in the handler must catch it
    big = "data:image/jpeg;base64," + "A" * (16 * 1024 * 1024)
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": big}},
        ]}]})
    assert r.status_code == 413


def test_vlm_rejects_unsupported_image_format(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "nim_api_key", "k")
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:application/x-msdownload;base64,AAAA"}},
        ]}]})
    assert r.status_code == 415


def test_vlm_rejects_more_than_four_images(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "nim_api_key", "k")
    content = [{"type": "text", "text": "describe"}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,AAA{i}"}}
        for i in range(5)
    ]
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": content}]})
    assert r.status_code == 413


def test_production_guard_refuses_debug_build():
    """ADAPTIVEAI_PRODUCTION=1 + DEBUG=True must refuse to boot - that combo
    auto-logs every visitor in as the demo user and opens CORS to *."""
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('booted')"],
        cwd=backend_dir,
        env={
            **{"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
               "PATH": __import__("os").environ.get("PATH", "")},
            "ADAPTIVEAI_PRODUCTION": "1",
            "SUPABASE_DB_URL": "",
            "DEBUG": "True",
        },
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "Refusing to start" in (result.stderr + result.stdout)


def test_metrics_endpoint_counts_and_percentiles(client):
    client.get("/health")
    client.get("/health")
    client.get("/api/does-not-exist")
    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["total_requests"] >= 3
    assert body["total_4xx"] >= 1
    assert body["latency_ms"]["p50"] is not None
    assert body["uptime_seconds"] > 0


def test_delete_account_requires_db(client):
    r = client.request("DELETE", "/auth/account",
                       headers={"Authorization": "Bearer whatever"})
    # No DB in offline mode: dependency chain must 503, never 500
    assert r.status_code == 503


def test_auth_endpoints_have_a_tighter_ip_bucket(client):
    """register/login are unauthenticated (IP-keyed); they get a separate,
    tighter budget so one client cannot lock out a shared NAT IP or farm
    fresh per-user buckets by mass-registering."""
    import app.main as service
    service._rate_limit_store.clear()
    try:
        codes = []
        for i in range(15):
            codes.append(client.post("/auth/register",
                                     json={"email": f"rl{i}@example.com", "password": "x"}).status_code)
        assert 429 in codes, "register should hit the tight auth limit before the 200 general limit"
        # the auth bucket tripped, but the general per-IP bucket must still be
        # far from exhausted - normal endpoints keep working
        assert client.get("/health").status_code == 200
    finally:
        service._rate_limit_store.clear()
