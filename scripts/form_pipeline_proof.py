"""Live proof: the Discovery -> Cache -> Replay -> Heal pipeline on a real page.

Runs against the compose stack (backend :8000 + the demo-forms static service):

  1. fill the ticket-booking demo            -> DISCOVER, cache, fill, submit
  2. the site "redesigns" (ids and placeholders drop, markup re-nests) and the
     same page is filled again with replay=true -> the cached selectors are now
     stale, REPLAY fails, HEAL relocates every field by its accessible label on
     the LIVE page, and the retry succeeds
  3. fill once more, same markup             -> pure REPLAY (no heal, no discovery)

The mutated page is written back from the original in a finally block, so the
repository is unchanged either way.

Usage:
  docker compose --profile demo up -d demo-forms
  python scripts/form_pipeline_proof.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_FILE = os.path.join(HERE, os.pardir, "demo", "book-tickets.html")
BACKEND = os.environ.get("ADAPTIVEAI_BACKEND_URL", "http://localhost:8000").rstrip("/")
DEMO_URL = os.environ.get("ADAPTIVEAI_DEMO_URL",
                          "http://demo-forms:8080/book-tickets.html")


def guard() -> None:
    """This proof talks to this repo's own demo page and writes only to the
    demo file inside the repository - enforced, not assumed. DEMO_URL comes
    from the environment; pointed anywhere else, the backend would fetch a
    stranger's page with our form values in it."""
    host = (urllib.parse.urlparse(DEMO_URL).hostname or "").lower()
    assert host in ("127.0.0.1", "localhost", "::1", "demo-forms"), \
        f"proof targets the compose demo service only, got {host!r}"
    repo = os.path.realpath(os.path.join(HERE, os.pardir))
    assert os.path.realpath(DEMO_FILE).startswith(repo + os.sep), \
        "the demo file must stay inside the repository"

VALUES = {
    "Passenger name (required)": "Asha Sharma",
    "Email address": "asha@real.test",
    "From station": "New Delhi",
    "To station": "Chandigarh",
    "Travel date": "2026-10-02",
    "Seats": "2",
    "Sleeper": "on",
    "Book tickets": "",
}


def fill(replay: bool) -> dict:
    body = json.dumps({"url": DEMO_URL, "values": VALUES, "replay": replay}).encode()
    request = urllib.request.Request(f"{BACKEND}/api/form-fill", data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


FIELD_IDS = ("pname", "pemail", "from", "to", "date", "seats")


def redesign(html: str) -> str:
    """A plausible site update: the FIELD ids (and their label `for=` partners)
    get renamed, placeholders disappear, and the form is re-nested in new
    elements so every positional path moves. The form's own script hooks are
    kept - a real redesign still wants its JS to work. The accessible NAME of
    each field survives, because that is what a screen reader reads, so a
    redesign that keeps the form usable for a blind user is exactly the case
    healing has to handle.
    """
    for name in FIELD_IDS:
        # Rename everywhere the id appears - the page's own script looks the
        # fields up by id, and a real refactor updates its own hooks. Without
        # this the submit handler would crash and the run would prove nothing.
        html = html.replace(f'"{name}"', f'"v2-{name}"').replace(f"'{name}'", f"'v2-{name}'")
    html = re.sub(r'\s+placeholder="[^"]*"', "", html)
    html = html.replace('<form', '<div class="booking-v2"><section class="fields"><form', 1)
    return html.replace('</form>', '</form></section></div>')


def show(label: str, result: dict) -> None:
    healed = result.get("healed") or {}
    print(f"\n{label}")
    print(f"  status         : {result.get('status')}")
    print(f"  action         : {result.get('action')}")
    print(f"  filled         : {result.get('success_count')} ok / {result.get('failure_count')} failed")
    if result.get("unfilled"):
        print(f"  unfilled       : {result['unfilled']}")
    print(f"  episode_id     : {result.get('episode_id')}")
    if result.get("page_message"):
        print(f"  page said      : {result['page_message'][:200]}")
    for action in result.get("replay_results", []):
        if action.get("status") != "success":
            print(f"    [{action.get('status')}] {action.get('label')!r} "
                  f"{str(action.get('reason', ''))[:110]}")
    if healed:
        print(f"  healed         : {healed.get('status')}, "
              f"{healed.get('repaired_fields')}/{healed.get('stale_fields')} stale fields relocated")
        for repair in healed.get("repairs", []):
            print(f"    - {repair['label']!r}: {repair['old_selector']!r} -> {repair['new_selector']!r}")


def main() -> int:
    guard()
    # Bytes, not text: a Windows text-mode round trip would rewrite every
    # newline and leave the repository dirty after a "read-only" proof.
    with open(DEMO_FILE, "rb") as handle:
        original = handle.read()

    try:
        print(f"target: {DEMO_URL}\nbackend: {BACKEND}")
        first = fill(replay=False)
        show("1) first visit - discover, cache, fill", first)

        with open(DEMO_FILE, "wb") as handle:
            handle.write(redesign(original.decode("utf-8")).encode("utf-8"))
        time.sleep(1)  # let the static server see the new file
        print("\n   [site redesigned: ids + placeholders removed, fields re-nested]")

        second = fill(replay=True)
        show("2) after the redesign - replay fails, heal relocates, retry", second)

        third = fill(replay=True)
        show("3) again on the same markup - pure replay", third)

        checks = {
            "first visit filled the form": first.get("success_count", 0) >= 8,
            "the site's own booking message was read back": "Booked" in first.get("page_message", ""),
            "redesign was healed, not re-discovered": bool(second.get("healed"))
            and second["healed"].get("status") == "repaired",
            "heal relocated stale selectors onto live fields": bool(
                (second.get("healed") or {}).get("repairs")),
            "healed replay booked again": second.get("failure_count") == 0
            and "Booked" in second.get("page_message", ""),
            "third run replayed without healing": "healed" not in third
            and third.get("action") == "replay_complete",
            "nothing was left silently unfilled": not first.get("unfilled")
            and not second.get("unfilled"),
        }
        print("\nchecks:")
        for name, ok in checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        return 0 if all(checks.values()) else 1
    finally:
        with open(DEMO_FILE, "wb") as handle:
            handle.write(original)
        with open(DEMO_FILE, "rb") as handle:
            identical = handle.read() == original
        print(f"\n[demo page restored, byte-identical: {identical}]")
        if not identical:
            print("  WARNING: the demo file did not come back unchanged")
            return 1


if __name__ == "__main__":
    sys.exit(main())
