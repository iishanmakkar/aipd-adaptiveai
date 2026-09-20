"""Guided fill + booking proof on ANY page the user opens.

Drives the REAL backend chat path (register -> session -> conversational
turns) on two deliberately different local demo pages:
  1. demo/gov-form-demo.html  - citizen grievance form (textarea, select,
     checkbox; different labels/layout from the ticket form)
  2. demo/book-tickets-monitored.html - train ticket booking (text, email,
     select, radios)
No selectors are hardcoded: the slot-fill loop reads each page's live DOM and
asks for every real field by label, then locates the page's real submit
control and holds it behind the explicit confirmation.

Env: ADAPTIVEAI_BACKEND_URL, ADAPTIVEAI_BROWSER_URL (http/https, validated;
ADAPTIVEAI_ALLOW_LOCAL_TARGET=1 for the local compose stack).
"""
import base64
import json
import os
import secrets
import time
import urllib.parse


def _service_url(env_name: str) -> str:
    raw = os.environ.get(env_name, "")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit(f"{env_name} is required and must be an http(s) URL")
    import ipaddress
    import socket
    try:
        for info in socket.getaddrinfo(parsed.hostname, None):
            if not ipaddress.ip_address(info[4][0]).is_global:
                if os.environ.get("ADAPTIVEAI_ALLOW_LOCAL_TARGET") != "1":
                    raise SystemExit(
                        f"{env_name} is private/loopback; set "
                        "ADAPTIVEAI_ALLOW_LOCAL_TARGET=1 to allow local proofs")
                break
    except OSError:
        raise SystemExit(f"{env_name}: cannot resolve host {parsed.hostname}")
    return raw.rstrip("/")


BACKEND = _service_url("ADAPTIVEAI_BACKEND_URL")
BROWSER = _service_url("ADAPTIVEAI_BROWSER_URL")


def req(url, payload=None, method=None, token=None, timeout=180):
    import httpx
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.request(
            method or ("POST" if payload is not None else "GET"),
            url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPStatusError as e:
        return {"_status": e.response.status_code, "_body": e.response.text[:200]}
    if resp.status_code >= 400:
        return {"_status": resp.status_code, "_body": resp.text[:200]}
    return resp.json()


def data_url(path):
    html = open(path, "rb").read()
    return "data:text/html;base64," + base64.b64encode(html).decode()


def guided_fill(token, sid, page_path, answers):
    """Open the page through chat, then answer the slot-fill loop."""
    print(f"   turn 1 (open + fill request):")
    r = req(f"{BACKEND}/api/query", {
        "session_id": sid,
        "input_text": f"Open this page and fill the form for me: {data_url(page_path)}",
        "input_source": "voice", "screen_context": "",
    }, token=token)
    print("     A:", r.get("response_text", r)[:150].replace("\n", " "))
    for i, value in enumerate(answers, start=2):
        r = req(f"{BACKEND}/api/query", {
            "session_id": sid, "input_text": value,
            "input_source": "voice", "screen_context": "",
        }, token=token)
        print(f"   turn {i} ('{value}'):")
        print("     A:", r.get("response_text", r)[:200].replace("\n", " "))
        if "Booked" in r.get("response_text", "") or "Grievance" in r.get("response_text", ""):
            return r.get("response_text", "")
    # submit-class control is held: explicit confirmation
    r = req(f"{BACKEND}/api/query", {
        "session_id": sid, "input_text": "submit",
        "input_source": "voice", "screen_context": "",
    }, token=token)
    print("   turn N ('submit'):")
    print("     A:", r.get("response_text", r)[:250].replace("\n", " "))
    return r.get("response_text", "")


def main():
    email = f"r9site{int(time.time())}@example.com"
    password = secrets.token_urlsafe(16) + "!A1"
    reg = req(f"{BACKEND}/auth/register",
              {"email": email, "password": password, "name": "Any Site Proof"})
    token = (reg.get("access_token") or req(
        f"{BACKEND}/auth/login", {"email": email, "password": password}
    ).get("access_token"))
    print("== auth ok")
    sid = req(f"{BACKEND}/api/session", {}, token=token)["session_id"]
    print("== chat session:", sid[:8])

    print("== SITE 1: citizen grievance form (different layout/labels)")
    guided_fill(token, sid, "demo/gov-form-demo.html",
                ["Ravi Kumar", "9876543210", "roads",
                 "Street light not working near block 4 for two weeks."])

    print("== SITE 2: train ticket booking (text, email, select, radios)")
    sid2 = req(f"{BACKEND}/api/session", {}, token=token)["session_id"]
    guided_fill(token, sid2, "demo/book-tickets-monitored.html",
                ["Asha Sharma", "asha@example.com", "2", "skip"])


if __name__ == "__main__":
    main()
