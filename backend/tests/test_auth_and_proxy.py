"""Auth primitives, the VLM proxy, and STT configuration errors."""
import pytest
from jose import JWTError, jwt

from app.api import routes_vlm
from app.api.auth import create_access_token, get_password_hash, verify_password
from app.config import settings


# --- password + token primitives -------------------------------------------

def test_password_hash_roundtrip():
    hashed = get_password_hash("demo123")
    assert hashed != "demo123"
    assert verify_password("demo123", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_hashes_are_salted():
    assert get_password_hash("same") != get_password_hash("same")


def test_access_token_carries_subject():
    token = create_access_token({"sub": "user-1"})
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "user-1"
    assert "exp" in payload


def test_tampered_token_is_rejected():
    token = create_access_token({"sub": "user-1"})
    with pytest.raises(JWTError):
        jwt.decode(token + "x", settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def test_expired_token_is_rejected():
    from datetime import timedelta
    token = create_access_token({"sub": "user-1"}, expires_delta=timedelta(seconds=-30))
    with pytest.raises(JWTError):
        jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --- VLM proxy --------------------------------------------------------------

class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, sink, response):
        self.sink = sink
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.sink.append({"url": url, "json": json, "headers": headers})
        return self.response


@pytest.fixture
def nim(monkeypatch):
    def install(status=200, payload=None):
        calls = []
        payload = payload or {"choices": [{"message": {"content": "a form with 3 fields"}}]}
        monkeypatch.setattr(routes_vlm.httpx, "AsyncClient",
                            lambda **kw: _Client(calls, _Resp(status, payload)))
        return calls
    return install


def test_vlm_forwards_to_nim_with_server_key(client, nim, monkeypatch):
    monkeypatch.setattr(settings, "nim_api_key", "nvapi-server-side")
    monkeypatch.setattr(settings, "nim_base_url", "https://integrate.api.nvidia.com/v1")
    calls = nim()

    body = {"model": "meta/llama-3.2-11b-vision-instruct",
            "messages": [{"role": "user", "content": "describe"}]}
    r = client.post("/v1/chat/completions", json=body)

    assert r.status_code == 200
    assert calls[0]["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer nvapi-server-side"
    assert calls[0]["json"]["model"] == "meta/llama-3.2-11b-vision-instruct"


def test_vlm_prefers_client_supplied_bearer(client, nim, monkeypatch):
    monkeypatch.setattr(settings, "nim_api_key", "nvapi-server-side")
    calls = nim()
    r = client.post("/v1/chat/completions",
                    json={"messages": []},
                    headers={"Authorization": "Bearer nvapi-frontend"})
    assert r.status_code == 200
    assert calls[0]["headers"]["Authorization"] == "Bearer nvapi-frontend"


def test_vlm_defaults_the_model_when_omitted(client, nim, monkeypatch):
    monkeypatch.setattr(settings, "nim_api_key", "k")
    calls = nim()
    client.post("/v1/chat/completions", json={"messages": []})
    assert calls[0]["json"]["model"] == "meta/llama-3.2-11b-vision-instruct"


def test_vlm_without_any_key_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "nim_api_key", "")
    monkeypatch.delenv("NIM_API_KEY", raising=False)
    r = client.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 503


def test_vlm_invalid_json_is_400(client, monkeypatch):
    monkeypatch.setattr(settings, "nim_api_key", "k")
    r = client.post("/v1/chat/completions", content=b"not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_vlm_passes_upstream_status_through(client, nim, monkeypatch):
    """A 401/404 from NIM must reach the caller untouched, not become a 200."""
    monkeypatch.setattr(settings, "nim_api_key", "k")
    nim(status=401, payload={"error": "Unauthorized"})
    r = client.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 401


def test_models_listing(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "meta/llama-3.2-11b-vision-instruct" in ids


# --- transcription ----------------------------------------------------------

def test_transcribe_rejects_empty_upload(client):
    r = client.post("/api/transcribe", files={"audio": ("a.webm", b"", "audio/webm")})
    assert r.status_code == 400


def test_transcribe_rejects_oversized_upload(client):
    r = client.post("/api/transcribe",
                    files={"audio": ("a.webm", b"x" * (10 * 1024 * 1024 + 1), "audio/webm")})
    assert r.status_code == 400


def test_transcribe_without_any_stt_backend_is_503(client, monkeypatch):
    """No faster-whisper and no cloud key must be an honest 503, never silence."""
    import app.api.routes_transcribe as rt
    monkeypatch.setattr(rt, "get_whisper_model", lambda: None)
    monkeypatch.setattr(settings, "nim_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/api/transcribe", files={"audio": ("a.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 503
    assert "STT not configured" in r.json()["detail"]
