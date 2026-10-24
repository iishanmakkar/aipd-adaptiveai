"""The extension's planner: page STRUCTURE in, one next action out.

Why this lives on the server and the action lives on the device: the model needs
the page, the device needs the user's values. So the request carries roles,
accessible names, states and value *kinds* - never a value - and the reply
carries a reference plus where the value should come from. A reply can say
"profile:email"; it cannot say "4111 1111 1111 1111" for a field the user never
spoke, because a model inventing a passenger name is indistinguishable from a
model stealing one.

Every rule below is enforced here, after the model answered, because the model's
output is untrusted input: refs must exist in the snapshot the caller sent,
literals must appear verbatim in the user's own goal, password fields are refused
even when asked for, and an unparseable or out-of-range reply becomes `cannot`
with a reason. A planner that is down says so; it does not guess.

There is deliberately no gate answer in this contract. The design doc asked for a
`gate_required` bool in the response; it is not here, because the only authority
is the deterministic local predicate in `extension/src/gate.js`, whose markers are
a list of case-insensitive regexes with an explanation attached. Re-implementing
that in Python would give a blind user two answers to "is this irreversible", and
the one they cannot override is the one that is a copy. A planner response cannot
clear the gate, and cannot pre-empt it either.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from openai import AsyncOpenAI

from app.config import settings

ACTIONS = ("fill", "click", "select", "focus")
EXPECTS = ("url_changed", "node_appears", "state_flipped", "title_changed",
           "announcement", "navigation_committed", "none")
STATUSES = ("act", "ask_user", "done", "cannot")

MAX_NODES_IN_PROMPT = 120
MAX_NARRATION_CHARS = 320

client = AsyncOpenAI(
    base_url=settings.nim_base_url,
    # No key is not a client error here: `complete()` reports "not configured"
    # and the route answers 503, so a keyless dev box gets a reason rather than
    # a crash at import time.
    api_key=settings.nim_api_key or "not-configured",
    timeout=settings.step_timeout_seconds,
    max_retries=1,
)


class PlannerUnavailable(Exception):
    """The model could not be reached or was not configured - reported, not guessed."""


async def complete(messages: List[Dict[str, str]]) -> str:
    """One chat completion, as raw text. Raises PlannerUnavailable on any failure."""
    try:
        response = await client.chat.completions.create(
            model=settings.nim_model,
            messages=messages,
            temperature=0.1,
            max_tokens=500,
        )
    except Exception as e:  # openai raises a dozen types; all mean "no plan"
        raise PlannerUnavailable(f"{type(e).__name__}: {str(e)[:160]}") from e
    try:
        return (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError) as e:
        raise PlannerUnavailable(f"malformed completion ({e})") from e


def _node_line(node: Dict[str, Any]) -> str:
    parts = [f"ref={node['ref']}", f"role={node.get('role') or 'generic'}"]
    name = (node.get("name") or "").strip()
    parts.append(f'name="{name}"' if name else "name=UNNAMED")
    if node.get("kind"):
        parts.append(f"kind={node['kind']}")
    if node.get("hasValue"):
        parts.append("has-value")
    if node.get("disabled"):
        parts.append("disabled")
    for state, on in sorted((node.get("states") or {}).items()):
        if on and state != "disabled":
            parts.append(state)
    if node.get("inShadow"):
        parts.append("shadow-dom")
    options = [str(o.get("text", "")) for o in (node.get("options") or [])][:12]
    if options:
        parts.append("options=" + " / ".join(options))
    return " ".join(parts)


SYSTEM_PROMPT = """You are the planner for a browser extension that acts for a blind \
user on the user's own logged-in page. You see the page only as an accessibility \
snapshot: refs, roles, accessible names, states and value KINDS. You never see and \
never receive a value anyone typed.

Answer with ONE json object and nothing else:
{"status":"act|ask_user|done|cannot","action":"fill|click|select|focus|null",\
"ref":"<a ref from the snapshot, or null>","value_from":"profile|literal|none",\
"value_label":"<one of available_labels, or null>",\
"value_literal":"<text, only if it appears verbatim in the goal, else null>",\
"expect":"url_changed|node_appears|state_flipped|title_changed|announcement|\
navigation_committed|none","narration":"<one short sentence to say aloud>",\
"why":"<reason, required unless status is act>"}

Hard rules. Breaking one is worse than failing the task:
- `ref` MUST be one of the refs given. There is no other ref. If none fits, \
status=cannot.
- Never fill, read or target a field with kind=password. If the task needs one, \
status=ask_user and say the user must type it themselves.
- `value_from":"profile"` for personal details (name, email, phone, address, \
passport, date of birth). Use `value_from":"literal"` ONLY for something the user \
already said in the goal, word for word. Never invent a name, number, date, city, \
seat or quantity. If the value is not in the goal and not in available_labels, \
status=ask_user and ask for it.
- One step. Choose the single next action, not a plan of many.
- `expect` describes how the user will be able to TELL the action worked: a page \
change you can observe. Use none for typing into a field.
- narration is spoken to a blind user: no "here", "above", "the button on the \
right". Name things by their accessible name.
- status=done only when the goal is actually achieved on this page. If a payment \
or final confirmation is the only thing left, status=ask_user and stop there.
"""


def build_messages(goal: str, page: Dict[str, Any], nodes: List[Dict[str, Any]],
                   available_labels: List[str], history: List[Dict[str, Any]],
                   verbosity: str) -> List[Dict[str, str]]:
    interactive = [n for n in nodes if n.get("interactive") or n.get("kind")
                   or n.get("live")]
    shown = interactive[:MAX_NODES_IN_PROMPT]
    lines = [f"goal: {goal}",
             f"page: {page.get('url', '')} title: {page.get('title', '')}",
             f"available_labels (stored on this device, values never sent): "
             f"{', '.join(available_labels) or '(none)'}"]
    if verbosity == "blind_concise":
        lines.append("verbosity: one short sentence, no reassurance")
    elif verbosity == "detailed":
        lines.append("verbosity: explain what you are about to do and why")
    if len(interactive) > len(shown):
        lines.append(f"snapshot truncated: {len(interactive) - len(shown)} more "
                     f"interactive nodes not shown")
    lines.append("snapshot:")
    lines.extend("  " + _node_line(n) for n in shown)
    if history:
        lines.append("already done:")
        for h in history[-12:]:
            lines.append(f"  {h.get('action') or '?'} {h.get('ref') or '?'} -> "
                         f"{h.get('status') or '?'}"
                         + (f" [{h['source']}]" if h.get("source") else "")
                         + (f" ({h['change']})" if h.get("change") else "")
                         + (f" error={h['error']}" if h.get("error") else ""))
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)}]


_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_reply(text: str) -> Dict[str, Any]:
    """Extract the object a small model actually returned, fences and all.

    A model that adds prose around the JSON is not wrong often enough to lose the
    step over, so the first balanced-looking object is taken. Everything else
    stays strict.
    """
    if not text:
        raise ValueError("empty reply")
    match = _JSON.search(text)
    if not match:
        raise ValueError("reply contained no json object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid json: {str(e)[:80]}") from e
    if not isinstance(data, dict):
        raise ValueError("reply json was not an object")
    return data


def _spoken_in_goal(literal: str, goal: str) -> bool:
    """Case/whitespace-insensitive containment in the user's own words."""
    needle = re.sub(r"\s+", " ", (literal or "").strip().lower())
    if not needle:
        return False
    haystack = re.sub(r"\s+", " ", (goal or "").strip().lower())
    return needle in haystack


def validate_plan(raw: Dict[str, Any], *, goal: str, nodes: List[Dict[str, Any]],
                  available_labels: List[str]) -> Dict[str, Any]:
    """Turn an untrusted model object into a reply the device may act on.

    The order is deliberate: identity, then refusal categories, then values, then
    narration. Anything that cannot be checked becomes `cannot`, because a step
    the runner invents is how an assistant ends up pressing the wrong button.
    """
    by_ref = {n["ref"]: n for n in nodes if isinstance(n, dict) and n.get("ref")}
    labels = {l.strip().lower() for l in available_labels if l and l.strip()}

    def cannot(why: str, narration: str | None = None) -> Dict[str, Any]:
        return {"status": "cannot", "action": None, "ref": None,
                "value_from": "none", "value_label": None, "value_literal": None,
                "expect": "none",
                "narration": narration or f"I could not work out the next step: {why}",
                "confidence_source": "llm", "why": why}

    status = str(raw.get("status") or "").strip().lower()
    if status not in STATUSES:
        return cannot(f"model returned an unknown status {status!r}")

    def finish(reply: Dict[str, Any]) -> Dict[str, Any]:
        base = {"status": status, "action": None, "ref": None, "value_from": "none",
                "value_label": None, "value_literal": None, "expect": "none",
                "narration": str(raw.get("narration") or "").strip()[:MAX_NARRATION_CHARS],
                "confidence_source": "llm",
                "why": str(raw.get("why") or "").strip()[:300] or None}
        base.update(reply)
        if not base["narration"]:
            base["narration"] = base["why"] or "I have nothing to report."
        return base

    if status in ("ask_user", "done", "cannot"):
        return finish({})

    action = str(raw.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return finish({"status": "cannot", "why": f"unknown action {action!r}",
                       "narration": f"I could not work out the next step: "
                                    f"unknown action {action!r}."})
    ref = str(raw.get("ref") or "").strip()
    node = by_ref.get(ref)
    if node is None:
        # The single most dangerous failure a planner can have: a ref that is not
        # on the page. The actor would answer stale_ref; refusing here keeps the
        # narration honest and the step count down.
        return finish({"status": "cannot", "ref": None,
                       "why": f"ref {ref!r} is not in the snapshot",
                       "narration": "I could not work out the next step: I named a "
                                    "control that is not on this page."})
    if node.get("kind") == "password" or node.get("sensitive"):
        return finish({"status": "cannot", "ref": None,
                       "why": "password fields are never read or filled",
                       "narration": "That field is a password. I never touch those - "
                                    "please type it yourself."})
    if node.get("disabled"):
        return finish({"status": "cannot", "ref": None,
                       "why": f"{node.get('role') or 'control'} is disabled",
                       "narration": f"The {node.get('role') or 'control'} I wanted is "
                                    "disabled right now."})

    expect = str(raw.get("expect") or "none").strip().lower()
    if expect not in EXPECTS:
        expect = "none"

    value_from = str(raw.get("value_from") or "none").strip().lower()
    label = str(raw.get("value_label") or "").strip().lower()
    literal = raw.get("value_literal")

    if action in ("click", "focus"):
        value_from, label, literal = "none", None, None
    elif value_from == "profile":
        if not label:
            return finish({"status": "cannot", "ref": None,
                           "why": "profile value requested with no label",
                           "narration": "I could not work out which of your details "
                                        "to use."})
        if label not in labels:
            # Not a failure of the plan - the plan is right, the vault is not
            # filled. Saying so lets the user fix it at the setup page.
            return finish({"status": "ask_user",
                           "why": f"no stored value for {label!r}",
                           "narration": f"I need your {label} and I do not have it "
                                        "saved. Add it in AdaptiveAI setup, or tell "
                                        "me what to enter."})
    elif value_from == "literal":
        if not _spoken_in_goal(str(literal or ""), goal):
            return finish({"status": "ask_user",
                           "why": "literal value was not in the goal",
                           "narration": f"What should I enter for "
                                        f"{node.get('name') or 'this field'}?"})
    else:
        if action in ("fill", "select"):
            return finish({"status": "ask_user",
                           "why": "no value source for a write action",
                           "narration": f"What should I enter for "
                                        f"{node.get('name') or 'this field'}?"})
        value_from, label, literal = "none", None, None

    return finish({"action": action, "ref": ref, "value_from": value_from,
                   "value_label": label, "value_literal": literal,
                   "expect": expect})


async def plan_step(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Plan one step. Never raises for a planning reason - only PlannerUnavailable."""
    messages = build_messages(
        payload["goal"], {"url": payload.get("url"), "title": payload.get("title")},
        payload.get("nodes") or [], payload.get("available_labels") or [],
        payload.get("history") or [], payload.get("verbosity") or "standard")
    raw = parse_reply(await complete(messages))
    return validate_plan(raw, goal=payload["goal"], nodes=payload.get("nodes") or [],
                         available_labels=payload.get("available_labels") or [])
