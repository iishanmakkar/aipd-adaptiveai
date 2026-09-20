"""Round 9 end-to-end chat-loop proof: monitoring + chat share one context.

Drives the REAL backend (:8000) as a registered user:
  open page via chat URL -> "watch my screen" voice command -> drive real page
  changes -> narrations pulled through /api/monitor/events (policy-adapted,
  persisted) -> follow-up chat question coherent with narrations ->
  "stop watching my screen" -> verify NO further NIM calls.

Targets default to the local compose stack and can be pointed elsewhere with
ADAPTIVEAI_BROWSER_URL / ADAPTIVEAI_BACKEND_URL (http/https only, validated).

Usage: python scripts/r9_chat_loop_proof.py
"""
import base64
import json
import os
import secrets
import time
import urllib.parse
import urllib.request


def _service_url(env_name: str) -> str:
    """Required target, http/https only, host validated before any request.

    Default-deny for private/loopback targets (same policy as the services):
    point the scripts at a public stack, or set ADAPTIVEAI_ALLOW_LOCAL_TARGET=1
    to explicitly opt in for driving the LOCAL compose stack under proof."""
    raw = os.environ.get(env_name, "")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit(
            f"{env_name} is required and must be an http(s) URL - for the "
            f"local compose stack set it to the backend/browser-agent address "
            f"(see docs/round9-monitoring.md)")
    import ipaddress
    import socket
    loopback = False
    try:
        for info in socket.getaddrinfo(parsed.hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if not addr.is_global:
                loopback = True
                break
    except OSError:
        raise SystemExit(f"{env_name}: cannot resolve host {parsed.hostname}")
    if loopback and os.environ.get("ADAPTIVEAI_ALLOW_LOCAL_TARGET") != "1":
        raise SystemExit(
            f"{env_name} resolves to a private/loopback address; set "
            f"ADAPTIVEAI_ALLOW_LOCAL_TARGET=1 to explicitly allow driving "
            f"the LOCAL compose stack")
    return raw.rstrip("/")


BACKEND = _service_url("ADAPTIVEAI_BACKEND_URL")
BROWSER = _service_url("ADAPTIVEAI_BROWSER_URL")


def req(url, payload=None, method=None, token=None, timeout=180):
    # Hosts were validated in _service_url before any URL is built here.
    import httpx
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.request(
            method or ("POST" if payload is not None else "GET"),
            url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPStatusError as e:
        return {"_status": e.response.status_code, "_body": e.response.text[:300]}
    if resp.status_code >= 400:
        return {"_status": resp.status_code, "_body": resp.text[:300]}
    return resp.json()


def data_url(path):
    html = open(path, "rb").read()
    return "data:text/html;base64," + base64.b64encode(html).decode()


def main():
    stamp = str(int(time.time()))
    email = f"r9proof{stamp}@example.com"
    # Throwaway per-run credential: the script registers a fresh user every
    # run, so nothing is shared and nothing is hardcoded.
    password = secrets.token_urlsafe(16) + "!A1"

    print("== 1. register + login (real auth)")
    reg = req(f"{BACKEND}/auth/register",
              {"email": email, "password": password, "name": "R9 Proof"})
    print("   register:", reg.get("access_token") is not None and "201 token"
          or reg)
    login = req(f"{BACKEND}/auth/login",
                {"email": email, "password": password})
    token = login["access_token"]
    print("   login: ok")

    print("== 2. create chat session")
    chat = req(f"{BACKEND}/api/session", {}, token=token)
    sid = chat["session_id"]
    print("   chat session:", sid[:8], "...")

    url = data_url("demo/book-tickets-monitored.html")
    print("== 3. open the page through chat (user-supplied URL)")
    r = req(f"{BACKEND}/api/query", {
        "session_id": sid,
        "input_text": f"I'm looking at this page: {url} where is the submit button?",
        "input_source": "text", "screen_context": "",
    }, token=token)
    print("   answer:", r["response_text"][:220].replace("\n", " "))

    print("== 4. voice command: 'watch my screen'")
    r = req(f"{BACKEND}/api/query", {
        "session_id": sid, "input_text": "watch my screen",
        "input_source": "voice", "screen_context": "",
    }, token=token)
    print("   answer:", r["response_text"][:200])
    mon = req(f"{BACKEND}/api/monitor/status?session_id={sid}", token=token)
    print("   monitor active:", mon.get("active"))

    print("== 5. drive a real change: submit with 4 seats -> validation error")
    for payload in ({"kind": "fill", "label": "Passenger name", "value": "Asha Sharma"},
                    {"kind": "fill", "label": "Seats", "value": "4"}):
        r = req(f"{BROWSER}/session/{sid}/act", payload)
        print("   act:", payload["label"], "->", json.dumps(r)[:120])
    prop = req(f"{BROWSER}/session/{sid}/act",
               {"kind": "click", "label": "Book tickets"})
    print("   click:", json.dumps(prop)[:120])
    if prop.get("status") == "needs_confirmation":
        r = req(f"{BROWSER}/session/{sid}/confirm",
                {"proposal_id": prop["proposal"]["proposal_id"]})
        print("   confirm:", json.dumps(r)[:160])
    c = req(f"{BROWSER}/session/{sid}/monitor/narrations?since=0")["stats"]["counters"]
    print("   monitor right after acts:", {k: c[k] for k in
          ("polls", "raw_activity", "changes_detected", "nim_calls")})
    print("   change triggered; waiting for narration to be pulled...")

    events = []
    deadline = time.time() + 90
    while time.time() < deadline and not events:
        time.sleep(4)
        ev = req(f"{BACKEND}/api/monitor/events?session_id={sid}&since=0",
                 token=token)
        events = ev.get("narrations", [])
    for e in events:
        ts = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
        print(f"   NARRATION [{ts}]: {e['text'][:200]}")
    if not events:
        print("   (no narration arrived - check monitor state)")
        print(req(f"{BROWSER}/session/{sid}/monitor/narrations?since=0"))

    print("== 6. follow-up chat question about what was just narrated")
    r = req(f"{BACKEND}/api/query", {
        "session_id": sid, "input_text": "what should I do about that error?",
        "input_source": "voice", "screen_context": "",
    }, token=token)
    print("   answer:", r["response_text"][:300].replace("\n", " "))

    print("== 7. stop via voice: 'stop watching my screen'")
    r = req(f"{BACKEND}/api/query", {
        "session_id": sid, "input_text": "stop watching my screen",
        "input_source": "voice", "screen_context": "",
    }, token=token)
    print("   answer:", r["response_text"][:200])
    before = req(f"{BROWSER}/session/{sid}/monitor/status")
    nim_before = (before.get("stats", {}).get("counters") or {}).get("nim_calls", "n/a")
    print("   monitor active after stop:", before.get("active"),
          "| nim_calls at stop:", nim_before)

    print("== 8. drive MORE changes after the stop - nothing may be narrated")
    req(f"{BROWSER}/session/{sid}/act",
        {"kind": "fill", "label": "Seats", "value": "3"})
    prop = req(f"{BROWSER}/session/{sid}/act",
               {"kind": "click", "label": "Book tickets"})
    if prop.get("status") == "needs_confirmation":
        req(f"{BROWSER}/session/{sid}/confirm",
            {"proposal_id": prop["proposal"]["proposal_id"]})
    time.sleep(30)  # > stable + ceiling window; a live monitor would have called
    after = req(f"{BROWSER}/session/{sid}/monitor/status")
    nim_after = (after.get("stats", {}).get("counters") or {}).get("nim_calls", "n/a")
    ev = req(f"{BACKEND}/api/monitor/events?session_id={sid}&since=0", token=token)
    print(f"   nim_calls before={nim_before} after={nim_after} "
          f"(must be equal); active={after.get('active')} "
          f"new_narrations={len(ev.get('narrations', []))}")
    print("== done")


if __name__ == "__main__":
    main()
