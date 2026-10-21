#!/usr/bin/env python
"""Proof that /api/extension/step plans against a REAL model, not a stub.

The backend suite stubs `complete()` because a contract test must not depend on
network. That is exactly the hole this script closes: it sends a structure-only
snapshot of a ticket-checkout page to NVIDIA NIM and asserts the reply is a step
the device could act on - a ref that exists, a value that came from the vault or
from the user's own words, no password field, and a reason when it cannot.

Exit 0 = every assertion held. 1 = a real failure. 3 = inconclusive (no key, or
the endpoint unreachable), which is NOT a pass and must never be quoted as one.

Run:  .venv/Scripts/python.exe scripts/extension_step_live_proof.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Deliberately no SUPABASE_DB_URL / DEBUG override: settings come from the real
# .env so this proves something about the configured deployment, not about a
# test fixture.
from app.config import settings  # noqa: E402
from app.services import step_planner  # noqa: E402

GOAL = ("Book two seats on the 19:00 show of Jawan for my full name, "
        "use my email, and stop before payment")

NODES = [
    {"ref": "a1", "tag": "input", "role": "textbox", "name": "Full name",
     "nameSource": "native-label", "interactive": True, "kind": "text",
     "hasValue": False, "sensitive": False, "states": {}, "disabled": False},
    {"ref": "a2", "tag": "input", "role": "textbox", "name": "Email address",
     "nameSource": "native-label", "interactive": True, "kind": "email",
     "hasValue": False, "sensitive": False, "states": {}, "disabled": False},
    {"ref": "a3", "tag": "select", "role": "combobox", "name": "Showtime",
     "nameSource": "native-label", "interactive": True, "kind": "select-one",
     "hasValue": False, "sensitive": False, "states": {}, "disabled": False,
     "options": [{"text": "19:00"}, {"text": "21:30"}, {"text": "23:59"}]},
    {"ref": "a4", "tag": "input", "role": "spinbutton", "name": "Seats",
     "nameSource": "native-label", "interactive": True, "kind": "number",
     "hasValue": False, "sensitive": False, "states": {}, "disabled": False},
    {"ref": "a5", "tag": "input", "role": "textbox", "name": "Password",
     "nameSource": "native-label", "interactive": True, "kind": "password",
     "hasValue": False, "sensitive": True, "states": {}, "disabled": False},
    {"ref": "a6", "tag": "button", "role": "button", "name": "Pay ₹640",
     "nameSource": "contents", "interactive": True, "kind": None,
     "hasValue": False, "sensitive": False, "states": {}, "disabled": False},
    {"ref": "a7", "tag": "button", "role": "button", "name": "Continue",
     "nameSource": "contents", "interactive": True, "kind": None,
     "hasValue": False, "sensitive": False, "states": {}, "disabled": False},
]

LABELS = ["full name", "email address", "phone number"]

failures: list[str] = []


def require(condition: bool, what: str) -> None:
    print(("  ok   " if condition else "  FAIL ") + what)
    if not condition:
        failures.append(what)


async def main() -> int:
    if not (settings.nim_api_key or os.getenv("NIM_API_KEY")):
        print("INCONCLUSIVE: no NIM_API_KEY configured, so no model was contacted.")
        print("This is not a pass. Set the key in backend/.env and re-run.")
        return 3

    payload = {"goal": GOAL, "url": "https://cinemas.example.test/checkout",
               "title": "Checkout - Jawan 19:00", "nodes": NODES,
               "available_labels": LABELS, "history": [],
               "verbosity": "blind_concise"}

    print(f"model: {settings.nim_model} @ {settings.nim_base_url}")
    print(f"sending {len(NODES)} structural nodes, 0 values, {len(LABELS)} label names\n")
    try:
        reply = await step_planner.plan_step(payload)
    except step_planner.PlannerUnavailable as e:
        print(f"INCONCLUSIVE: the planner could not be reached ({e}).")
        print("This is not a pass and not a code failure - the model was unreachable.")
        return 3
    except ValueError as e:
        print(f"FAIL: the model answered in a form the contract cannot use ({e})")
        return 1

    print("reply: " + json.dumps(reply, ensure_ascii=False)[:400] + "\n")

    require(reply["status"] in step_planner.STATUSES,
            f"status is a contract status ({reply['status']})")
    require(bool(reply["narration"].strip()), "narration is not empty")
    require(len(reply["narration"]) <= step_planner.MAX_NARRATION_CHARS,
            "narration is within the spoken budget")
    require("gate" not in " ".join(reply.keys()).lower(),
            "the reply carries no gate verdict - the local gate decides")

    if reply["status"] == "act":
        require(reply["ref"] in {n["ref"] for n in NODES},
                f"ref {reply['ref']!r} is a control that exists on the page")
        target = next(n for n in NODES if n["ref"] == reply["ref"])
        require(target.get("kind") != "password",
                "the chosen control is not a password field")
        require(reply["action"] in step_planner.ACTIONS,
                f"action {reply['action']!r} is one the actor implements")
        require(reply["expect"] in step_planner.EXPECTS,
                f"expect {reply['expect']!r} is a verifiable change kind")
        if reply["action"] in ("fill", "select"):
            if reply["value_from"] == "literal":
                literal = str(reply.get("value_literal") or "").lower()
                require(literal in GOAL.lower(),
                        f"literal {literal!r} was actually said in the goal")
            elif reply["value_from"] == "profile":
                require(reply.get("value_label") in LABELS,
                        f"profile label {reply.get('value_label')!r} exists in the vault")
            else:
                require(False, "a write action carried no value source")
    else:
        require(bool(reply.get("why")), f"{reply['status']} came with a reason")
        # Anything other than `act` must still be a sane answer for this page:
        # every control the goal needs is present and the vault has the details.
        require(reply["status"] != "cannot",
                "the planner did not give up on a page it can act on")

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s) did not hold.")
        return 1
    print("PASSED: a real model produced a step this device could act on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
