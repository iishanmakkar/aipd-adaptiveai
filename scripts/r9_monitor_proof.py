"""Round 9 live proof driver.

Drives the REAL stack (browser-agent :8003, backend :8000) and proves the
evidence used in docs/round9-monitoring.md: narration transcripts with
timestamps, monitor gate counters, and stop-then-verify-no-calls.

Every expectation below is an assertion and exits non-zero - a script that
cannot fail is not a proof. (Until 2026-10-21 this file printed "expected 0" and
"must be 1" and then returned 0 whether or not they held.)

Scope: the targets are this repo's OWN demo pages (demo/book-tickets-monitored.html
and demo/monitor-stress.html). They prove the monitor's gating, rate ceiling and
interrupt behaviour against a real Chromium DOM. They are NOT evidence about any
real vendor - no ticket is booked and no booking site is touched.

Targets come from the environment (no defaults - a wrong default would silently drive the wrong stack); point them at the local compose stack with
ADAPTIVEAI_BROWSER_URL / ADAPTIVEAI_BACKEND_URL (http/https only, validated).

Usage: python scripts/r9_monitor_proof.py <scenario>
Scenarios: gating | interruption | stress | fivemin
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def _require(cond, msg):
    """A proof that cannot fail is not a proof: report, then exit non-zero."""
    if cond:
        print(f"  ok: {msg}")
        return
    print(f"  FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


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
            f"local compose stack set it to the browser-agent/backend address "
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


BROWSER = _service_url("ADAPTIVEAI_BROWSER_URL")
BACKEND = _service_url("ADAPTIVEAI_BACKEND_URL")


def req(url, payload=None, method=None, timeout=120):
    # Hosts were validated in _service_url before any URL is built here.
    import httpx
    try:
        resp = httpx.request(
            method or ("POST" if payload is not None else "GET"),
            url, json=payload,
            headers={"Content-Type": "application/json"}, timeout=timeout)
    except httpx.HTTPStatusError as e:
        return {"_status": e.response.status_code, "_body": e.response.text[:300]}
    if resp.status_code >= 400:
        return {"_status": resp.status_code, "_body": resp.text[:300]}
    return resp.json()


def data_url(path):
    html = open(path, "rb").read()
    return "data:text/html;base64," + base64.b64encode(html).decode()


def open_session(session_id, page_path):
    return req(f"{BROWSER}/session/open",
               {"session_id": session_id, "url": data_url(page_path)})


def act(session_id, kind, label, value="", confirmed=False):
    return req(f"{BROWSER}/session/{session_id}/act",
               {"kind": kind, "label": label, "value": value,
                "confirmed": confirmed})


def narrations(session_id, since=0):
    return req(f"{BROWSER}/session/{session_id}/monitor/narrations?since={since}")


def show_narrations(session_id, since=0):
    pull = narrations(session_id, since)
    for ev in pull.get("events", []):
        ts = time.strftime("%H:%M:%S", time.localtime(ev["ts"]))
        print(f'  [{ts}] ({ev["trigger"]}) {ev["raw_description"]}')
    return pull.get("events", [])


def wait_for_narrations(session_id, expect, timeout_s, since=0):
    """Real NIM calls take 5-30s+; poll until events land or timeout."""
    deadline = time.time() + timeout_s
    seen = []
    while time.time() < deadline:
        seen = narrations(session_id, since).get("events", [])
        if len(seen) >= expect:
            return seen
        time.sleep(2.0)
    return seen


def fresh_session(session_id, page_path):
    # close is a POST route: an explicit method is required because a None
    # payload would otherwise default to GET (found live: silent 405).
    req(f"{BROWSER}/session/{session_id}/close", method="POST")
    return open_session(session_id, page_path)


def scenario_gating():
    sid = "r9-gating"
    print("== open live session on book-tickets-monitored.html")
    print(" ", fresh_session(sid, "demo/book-tickets-monitored.html")["status"])
    print("== explicit consent: start monitor")
    print(" ", req(f"{BROWSER}/session/{sid}/monitor/start",
                   {"requested_by": "voice"})["status"])

    time.sleep(3)
    print("== 1) fill the name field (typing only - expect NO narration)")
    print(" ", act(sid, "fill", "Passenger name", "Asha Sharma")["status"])
    time.sleep(6)
    pull = narrations(sid)
    counters = pull["stats"]["counters"]
    _require(counters["narrations"] == 0,
             f"a typing-only edit must not narrate (got {counters['narrations']})")
    print(f"  (nim_calls so far: {counters['nim_calls']})")

    def confirmed_click(label):
        prop = act(sid, "click", label)
        if prop.get("status") == "needs_confirmation":
            print(f"  confirm-gate held {label!r} (proposal "
                  f"{prop['proposal']['proposal_id']})")
            return req(f"{BROWSER}/session/{sid}/confirm",
                       {"proposal_id": prop["proposal"]["proposal_id"]})
        return prop

    print("== 2) demand 4 seats (only 3 remain) and submit -> real validation")
    print("    error appears under the seat field")
    print("  select seats=4:", act(sid, "fill", "Seats", "4")["status"])
    print("  submit:", confirmed_click("Book tickets").get("status"))
    events = wait_for_narrations(sid, expect=1, timeout_s=60)
    show_narrations(sid)
    _require(len(events) >= 1, "the seat-count validation error was never narrated")
    since = events[-1]["id"]

    print("== 3) reveal a new field (choose AC 3-tier -> meal field appears)")
    print("  radio:", act(sid, "click", "AC 3-tier")["status"])
    events = wait_for_narrations(sid, expect=1, timeout_s=90, since=since)
    shown = show_narrations(sid, since)
    _require(len(shown) >= 1, "a page change went unnarrated inside 90s")
    since = shown[-1]["id"]
    print("== 4) fix the seat count (error clears) and submit again -> booking")
    print("  select seats=2:", act(sid, "fill", "Seats", "2")["status"])
    print("  submit:", confirmed_click("Book tickets").get("status"))
    events = wait_for_narrations(sid, expect=1, timeout_s=90, since=since)
    shown = show_narrations(sid, since)
    _require(len(shown) >= 1, "a page change went unnarrated inside 90s")
    since = shown[-1]["id"]

    print("== final stats")
    stats = narrations(sid)["stats"]
    print(json.dumps(stats, indent=2))
    _require(stats["counters"]["nim_calls"] >= 1,
             "three real page changes narrated with zero vision calls - the "
             "narration did not come from the page")
    _require(stats["counters"]["narrations"] >= 3,
             f"expected one narration per page change, got {stats['counters']['narrations']}")
    req(f"{BROWSER}/session/{sid}/monitor/stop", {})
    return stats


def scenario_interruption():
    sid = "r9-interrupt"
    print("== open session + start monitor")
    fresh_session(sid, "demo/book-tickets-monitored.html")
    req(f"{BROWSER}/session/{sid}/monitor/start", {"requested_by": "button"})
    time.sleep(2)
    print("== submit with empty name -> validation error appears")
    prop = act(sid, "click", "Book tickets")
    if prop.get("status") == "needs_confirmation":
        req(f"{BROWSER}/session/{sid}/confirm",
            {"proposal_id": prop["proposal"]["proposal_id"]})
    print("== user speaks NOW -> the backend's chat path calls monitor/interrupt")
    t_user = time.time()
    req(f"{BROWSER}/session/{sid}/monitor/interrupt", {})
    print("  user turn at", time.strftime("%H:%M:%S", time.localtime(t_user)))
    events = wait_for_narrations(sid, expect=1, timeout_s=90)
    _require(len(events) >= 1, "no narration ever arrived after the user turn")
    t_narr = events[-1]["ts"]
    c = narrations(sid)["stats"]["counters"]
    print("  narration delivered at",
          time.strftime("%H:%M:%S", time.localtime(t_narr)),
          f'-> {events[-1]["raw_description"][:90]}')
    _require(c["deferred_by_quiet"] == 1,
             f"the user turn must defer exactly one narration, got "
             f"{c['deferred_by_quiet']}")
    _require(t_narr > t_user,
             f"narration fired at {t_narr} before the user turn at {t_user} - "
             f"it talked over the user instead of waiting for the quiet window")
    print(f"  narration landed {t_narr - t_user:.1f}s after the user turn")
    req(f"{BROWSER}/session/{sid}/monitor/stop", {})


def scenario_stress():
    sid = "r9-stress"
    print("== open session on the live-updating departures board")
    fresh_session(sid, "demo/monitor-stress.html")
    req(f"{BROWSER}/session/{sid}/monitor/start", {"requested_by": "button"})
    duration = 60
    print(f"== watching for {duration}s while the page mutates every 250ms")
    time.sleep(duration)
    stats = narrations(sid)["stats"]
    c = stats["counters"]
    print(f"  polls={c['polls']} raw_activity={c['raw_activity']} "
          f"changes={c['changes_detected']} rate_blocked={c['rate_blocked']} "
          f"minor={c['minor_ignored']} nim_calls={c['nim_calls']} "
          f"narrations={c['narrations']}")
    req(f"{BROWSER}/session/{sid}/monitor/stop", {})
    after = req(f"{BROWSER}/session/{sid}/monitor/status")
    print("== after stop, active:", after.get("active"))
    _require(c["polls"] > 0, "the monitor never polled a page that mutates every 250ms")
    _require(c["changes_detected"] > 0,
             f"no change detected on a page that changes 4x/second for {duration}s")
    _require(c["rate_blocked"] > 0,
             f"the rate ceiling never engaged despite continuous churn: {c}")
    _require(after.get("active") is False,
             "monitor still reports active after stop - it keeps spending NIM quota")
    return stats


def scenario_fivemin():
    sid = "r9-fivemin"
    print("== 5-minute monitored session doing normal form-filling work")
    fresh_session(sid, "demo/book-tickets-monitored.html")
    req(f"{BROWSER}/session/{sid}/monitor/start", {"requested_by": "voice"})
    t0 = time.time()
    # A realistic, slow form-filling conversation with idle gaps: the user
    # listens to narrations and acts every ~45s.
    script = [
        ("act", ("fill", "Passenger name", "Asha Sharma"), 45),
        ("act", ("fill", "Email address", "asha@example.com"), 45),
        ("act", ("click", "AC 3-tier"), 45),
        ("confirm", ("Book tickets",), 45),   # confirm-gated submit (books)
        ("act", ("fill", "Passenger name", "Ravi Kumar"), 45),
        ("act", ("fill", "Passenger name", "Ravi Verma"), 30),
    ]
    since = 0
    for kind, args, idle in script:
        target = t0 + 300 - 5  # everything fits inside 5 minutes
        if time.time() > target:
            break
        if kind == "act":
            act(sid, *args)
        else:
            prop = act(sid, "click", args[0])
            if prop.get("status") == "needs_confirmation":
                req(f"{BROWSER}/session/{sid}/confirm",
                    {"proposal_id": prop["proposal"]["proposal_id"]})
        time.sleep(min(idle, max(0, target - time.time())))
    elapsed = time.time() - t0
    time.sleep(2)
    stats = narrations(sid)["stats"]
    c = stats["counters"]
    print(f"== after {elapsed:.0f}s: polls={c['polls']} idle={c['polls_idle']} "
          f"raw_activity={c['raw_activity']} changes={c['changes_detected']} "
          f"minor={c['minor_ignored']} rate_blocked={c['rate_blocked']} "
          f"nim_calls={c['nim_calls']} narrations={c['narrations']} "
          f"errors={c['errors']}")
    print("== narration transcript (this session):")
    show_narrations(sid, 0)
    req(f"{BROWSER}/session/{sid}/monitor/stop", {})
    _require(c["polls"] > 0, "a 5-minute monitored session recorded zero polls")
    _require(elapsed > 240, f"soak ended after only {elapsed:.0f}s, not 5 minutes")
    return stats


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "gating"
    {"gating": scenario_gating,
     "interruption": scenario_interruption,
     "stress": scenario_stress,
     "fivemin": scenario_fivemin}[what]()
    print("\nall checks passed")
    raise SystemExit(0)

