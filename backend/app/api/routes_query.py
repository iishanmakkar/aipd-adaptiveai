from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import re
import time

from app.api.auth import get_current_user, get_current_user_optional
from app.api.deps import describe, parse_session_uuid
from app.config import settings
from app.database import get_db, is_db_available
from app.models.user import User
from app.models.session import Session
from app.models.message import Message, MessageRole
from app.models.preference import Preference
from app.models.behavior import BehaviorSignal
from app.schemas.query import QueryRequest, QueryResponse
from app.services.clients import (
    IntentResponse,
    classify_intent,
    get_agent_response,
    browser_open_session,
    browser_navigate,
    browser_inspect,
    browser_act,
    browser_confirm,
    browser_snapshot,
)
from app.services.policy_engine import adjust_response, count_clarifying_questions

router = APIRouter(prefix="/api", tags=["query"])

URL_RE = re.compile(r"https?://[^\s)]+|data:[^\s]+", re.IGNORECASE)
LIVE_MARKER_RE = re.compile(r"live page:[^(]*\((https?://[^)\s]+)\)", re.IGNORECASE)
CONFIRM_WORDS = ("yes", "submit", "confirm", "book it", "do it", "go ahead",
                 "proceed", "ok", "okay", "confirm submit")
CANCEL_WORDS = ("no", "cancel", "stop", "don't", "dont", "never mind", "abort")
PENDING_TTL_SECONDS = 300.0

# Held confirmations + known live pages, keyed by chat session id. In-memory
# with TTL, like the intent engine's session store: a restart drops held
# confirmations instead of firing stale ones - the safe default.
_pending: dict[str, dict] = {}
_live_pages: dict[str, str] = {}


def _get_pending(chat_id: str) -> dict | None:
    pending = _pending.get(chat_id)
    if pending is None:
        return None
    if time.time() - pending.get("created_at", 0) > PENDING_TTL_SECONDS:
        _pending.pop(chat_id, None)
        return None
    return pending


def _extract_url(text: str, screen_context: str | None) -> str | None:
    """The ONLY way a live page gets opened: a URL the user actually typed
    (message first, then the page-context marker). Never from RAG output,
    never guessed - that is the explicit-opt-in half of the safety policy."""
    if text:
        found = URL_RE.search(text)
        if found:
            # data: URLs from chat paste-ups can trail punctuation; strip it.
            return found.group(0).rstrip(").,.!?:;\"'")
    if screen_context:
        found = LIVE_MARKER_RE.search(screen_context)
        if found:
            return found.group(1)
    return None


def _is_confirm(text: str) -> bool:
    """Single words only count on exact match ("yes please tell me more" must
    NOT confirm a held submit); multi-word phrases may lead the message."""
    lowered = text.strip().lower()
    for words in CONFIRM_WORDS:
        if " " in words:
            if lowered.startswith(words):
                return True
        elif lowered == words:
            return True
    return False


def _is_cancel(text: str) -> bool:
    lowered = text.strip().lower()
    return any(w in lowered for w in CANCEL_WORDS)


def _is_exact_cancel(text: str) -> bool:
    """The WHOLE message is a cancel phrase - used while a slot-fill waits for
    a value, where free text like 'Street light not working' is field data,
    not a command (found live: the substring check ate such values)."""
    lowered = text.strip().lower().strip(".,!?;:")
    if lowered in CANCEL_WORDS:
        return True
    return lowered in ("cancel that", "cancel it", "no cancel", "stop that",
                       "stop it", "never mind", "nevermind", "abort")


# Round 9: voice commands for the page monitor. They must NOT collide with
# the cancel word "stop" alone - "stop" mid-slot-fill cancels a proposal;
# only the explicit watching-phrases toggle monitoring.
WATCH_START_PATTERNS = (
    "watch my screen", "watch the screen", "start watching", "watch this page",
    "monitor this page", "monitor my screen", "keep an eye on this page",
)
WATCH_STOP_PATTERNS = (
    "stop watching", "stop monitoring", "stop watching my screen",
    "stop watching the screen", "stop monitoring my screen",
    "stop the monitoring", "turn off monitoring", "turn off watching",
)


def _watch_command(text: str) -> str | None:
    """'start' | 'stop' | None from the user's phrasing."""
    lowered = text.strip().lower()
    if any(p in lowered for p in WATCH_STOP_PATTERNS):
        return "stop"
    if any(p in lowered for p in WATCH_START_PATTERNS):
        return "start"
    return None


async def _with_reopen(chat_id: str, url: str | None, request_id: str | None,
                       call):
    """Run a browser call; on 404 (session swept) re-open once from the known
    URL and retry. Anything else propagates."""
    import httpx
    try:
        return await call()
    except httpx.HTTPStatusError as e:
        is_404 = e.response is not None and e.response.status_code == 404
        if not is_404 or not url:
            raise
        await _ensure_live_session(chat_id, url, request_id)
        return await call()


async def _handle_browser_intent(db, session, current_user, session_uuid, request,
                                 intent_result, request_id,
                                 message_count) -> QueryResponse | None:
    """Route a browser_* intent at the chat session's live page. The page is
    guaranteed present here (URL was extracted or a session already open)."""
    chat_id = request.session_id
    url = _extract_url(request.input_text, request.screen_context)
    if url is not None and _live_pages.get(chat_id) != url:
        try:
            opened = await _ensure_live_session(chat_id, url, request_id)
        except HTTPException as e:
            return await _browser_answer(
                db, session, current_user, session_uuid,
                f"I couldn't open that page: {e.detail}",
                intent_result.intent, "live session open failed",
                intent_result.confidence, message_count)
        if isinstance(opened, dict) and opened.get("status") == "needs_confirmation":
            _pending[chat_id] = {
                "kind": "navigate", "proposal": opened["proposal"], "url": url,
                "intent_label": intent_result.intent,
                "confidence": intent_result.confidence,
                "created_at": time.time(),
            }
            return await _finish_turn(
                db, session, current_user, session_uuid,
                answer=(opened["proposal"]["summary"]
                        + " Reply 'yes, open it' to proceed, or 'cancel'."),
                agent_used="browser_agent", suggested_action="confirm_navigate",
                sources_used=[], confidence=intent_result.confidence,
                intent_label=intent_result.intent,
                reasoning="sensitive domain held for confirmation",
                message_count=message_count)
    live_url = _live_pages.get(chat_id) or url
    if live_url is None:
        return None  # caller demotes; unreachable given the guardrail above

    target = intent_result.extracted_entity or request.input_text
    if intent_result.intent == "browser_inspect":
        try:
            data = await _with_reopen(
                chat_id, live_url, request_id,
                lambda: browser_inspect(chat_id, target, request_id))
        except Exception as e:
            code, detail = _browser_error_detail(e)
            return await _browser_answer(
                db, session, current_user, session_uuid,
                f"I couldn't read the live page: {detail}.",
                "browser_inspect", "inspect failed",
                intent_result.confidence, message_count)
        return await _finish_turn(
            db, session, current_user, session_uuid,
            answer=_compose_inspect_answer(data, target),
            agent_used="browser_agent", suggested_action="none",
            sources_used=[], confidence=intent_result.confidence,
            intent_label="browser_inspect",
            reasoning=intent_result.reasoning,
            message_count=message_count,
        )

    # browser_act -> conversational slot-fill over the live page's real fields,
    # unless the user asked for a direct click ("click/press/tap X" with no
    # fill phrasing), which resolves the target and either clicks it (routine)
    # or holds it (submit-class) for confirmation.
    import re as _re
    _text_lower = (request.input_text or "").lower()
    _fillish = bool(_re.search(r"\b(fill|book|type|enter|complete|my\b|name is|email is|put|set)\b", _text_lower))
    _clickish = bool(_re.search(r"\b(click|press|tap|hit|push)\b", _text_lower))
    if _clickish and not _fillish:
        return await _direct_click_turn(
            db, session, current_user, session_uuid, chat_id, live_url,
            intent_result.extracted_entity or request.input_text,
            intent_result, request_id, message_count)
    try:
        snap = await _with_reopen(
            chat_id, live_url, request_id,
            lambda: browser_snapshot(chat_id, request_id))
    except Exception as e:
        _, detail = _browser_error_detail(e)
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"I couldn't read the live page: {detail}.",
            "browser_act", "snapshot failed",
            intent_result.confidence, message_count)
    fields = _fill_targets((snap.get("nodes") or []))
    if not fields:
        labels = [str(n.get("label", ""))[:60]
                  for n in (snap.get("nodes") or [])][:12]
        seen = "\n".join(f"- {label}" for label in labels if label) or "(no labelled elements)"
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"I have the page '{snap.get('title', '')}' open, but I can't see "
            f"any fillable text fields on it. What I do see:\n{seen}",
            "browser_act", "no fillable fields",
            intent_result.confidence, message_count)
    remaining = [{"label": f.get("label"), "selector": f.get("selector")}
                 for f in fields]
    _pending[chat_id] = {
        "kind": "fill_next", "remaining": remaining, "filled": [],
        "url": live_url,
        "intent_label": "browser_act", "confidence": intent_result.confidence,
        "created_at": time.time(),
    }
    first = remaining[0]["label"]
    return await _browser_answer(
        db, session, current_user, session_uuid,
        f"I have '{snap.get('title', 'the page')}' open with {len(remaining)} "
        f"fields to fill. What should go in '{first}'? (or say 'skip')",
        "browser_act", "slot fill started",
        intent_result.confidence, message_count)


def _compose_inspect_answer(data: dict, target: str) -> str:
    """Turn live inspect matches into the specific answer the old web_agent
    never gave: real labels, real positions, real neighbours."""
    title = data.get("title") or "the open page"
    matches = data.get("matches") or []
    if not matches:
        return (f"I looked at the live page '{title}' and nothing on it "
                f"matches '{target}'. Try different words for what you need.")
    top = matches[0]
    text = (f"On '{title}': '{top.get('label')}' ({top.get('role') or 'control'}) "
            f"is {top.get('position', 'on the page')}.")
    if top.get("before"):
        text += f" It comes right after '{top['before']}'."
    if top.get("after"):
        text += f" Next is '{top['after']}'."
    if len(matches) > 1:
        others = ", ".join(f"'{m.get('label')}'" for m in matches[1:3])
        text += f" There are {len(matches)} matches; others: {others}."
    return text


async def _hold_submit(db, session, current_user, session_uuid, chat_id,
                       selector: str, label: str, filled_summary: str,
                       confidence: float, message_count: int,
                       request_id) -> QueryResponse:
    """Shared submit gate: hold the click as a single-use proposal."""
    _pending[chat_id] = {
        "kind": "submit",
        "proposal": {"proposal_id": "", "payload": {"selector": selector}},
        "intent_label": "browser_act", "confidence": confidence,
        "created_at": time.time(),
    }
    # Ask the browser-agent for the real proposal object (single-use id) via
    # a dry act call: submit-class targets always come back held.
    try:
        held = await browser_act(chat_id, "click", label=label,
                                 selector=selector, request_id=request_id)
    except Exception as e:
        _pending.pop(chat_id, None)
        _, detail = _browser_error_detail(e)
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"I found '{label}' but couldn't hold it for confirmation: {detail}. "
            "Nothing was submitted.",
            "browser_act", "submit hold failed", confidence, message_count)
    if not isinstance(held, dict) or held.get("status") != "needs_confirmation":
        _pending.pop(chat_id, None)
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"Unexpected submit state ({held}) - nothing was clicked. Tell me again what to do.",
            "browser_act", "submit hold failed", confidence, message_count)
    _pending[chat_id]["proposal"] = held["proposal"]
    prefix = f"{filled_summary}\n\n" if filled_summary else ""
    return await _finish_turn(
        db, session, current_user, session_uuid,
        answer=(f"{prefix}I'm holding before '{label}' - say 'submit' to actually "
                "click it, or 'cancel'. Nothing has been submitted yet."),
        agent_used="browser_agent", suggested_action="confirm_submit",
        sources_used=[], confidence=confidence,
        intent_label="browser_act",
        reasoning="submit held for explicit confirmation",
        message_count=message_count)


async def _direct_click_turn(db, session, current_user, session_uuid, chat_id,
                             live_url, target, intent_result, request_id,
                             message_count) -> QueryResponse:
    """'Click/press/tap X' with no fill phrasing: resolve once, click routine
    targets immediately, hold submit-class ones for confirmation."""
    try:
        data = await _with_reopen(
            chat_id, live_url, request_id,
            lambda: browser_inspect(chat_id, target, request_id))
    except Exception as e:
        _, detail = _browser_error_detail(e)
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"I couldn't read the live page: {detail}.",
            "browser_act", "inspect failed",
            intent_result.confidence, message_count)
    matches = data.get("matches") or []
    if not matches:
        return await _browser_answer(
            db, session, current_user, session_uuid,
            _compose_inspect_answer(data, target)
            + " Tell me which one to click, if any.",
            "browser_act", "click target not found",
            intent_result.confidence, message_count)
    top = matches[0]
    if top.get("submit_action"):
        return await _hold_submit(
            db, session, current_user, session_uuid, chat_id,
            top.get("selector", ""), top.get("label", target), "",
            intent_result.confidence, message_count, request_id)
    try:
        result = await _with_reopen(
            chat_id, live_url, request_id,
            lambda: browser_act(chat_id, "click", label=top.get("label"),
                                selector=top.get("selector"),
                                request_id=request_id))
    except Exception as e:
        _, detail = _browser_error_detail(e)
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"I found '{top.get('label')}' but the click failed: {detail}.",
            "browser_act", "click failed",
            intent_result.confidence, message_count)
    return await _browser_answer(
        db, session, current_user, session_uuid,
        f"Clicked '{top.get('label')}' ({top.get('position', 'on the page')}).",
        "browser_act", "routine click executed",
        intent_result.confidence, message_count)


async def _browser_answer(db, session, current_user, session_uuid, text: str,
                          intent_label: str, reasoning: str, confidence: float,
                          message_count: int) -> QueryResponse:
    """Finish helper with browser-agent attribution (no KB sources: the live
    page grounded it, and the element labels are quoted in the text)."""
    return await _finish_turn(
        db, session, current_user, session_uuid,
        answer=text, agent_used="browser_agent", suggested_action="none",
        sources_used=[], confidence=confidence,
        intent_label=intent_label, reasoning=reasoning,
        message_count=message_count,
    )


def _fill_targets(nodes: list) -> list:
    """Fillable controls in page order (text-likes + dropdowns). Radios,
    checkboxes, buttons and hidden inputs are out of scope for slot-fill v1:
    the proposal names anything left untouched instead of guessing."""
    targets = []
    for node in nodes:
        tag = str(node.get("tag", "")).lower()
        kind = str(node.get("type", "")).lower()
        label = str(node.get("label", "")).strip()
        if not label or not node.get("selector"):
            continue
        if tag == "textarea":
            targets.append(node)
        elif tag == "select":
            targets.append(node)
        elif tag == "input" and kind in ("", "text", "email", "date", "number",
                                         "tel", "url", "search", "password"):
            targets.append(node)
    return targets


async def _maybe_browser_turn(db, session, current_user, session_uuid, request,
                              request_id, message_count) -> QueryResponse | None:
    """Handle live-browser turns. Returns a response when the turn is fully
    handled here, else None to continue down the normal intent->agent path."""
    chat_id = request.session_id
    text = (request.input_text or "").strip()

    # 0. Round 9 monitor voice commands - before anything else so "stop
    # watching my screen" can never collide with a held submit's cancel word.
    # Every user turn also asserts priority over narrations (quiet window),
    # so the assistant never talks over the user.
    from app.services.clients import browser_monitor_interrupt
    if _live_pages.get(chat_id):
        try:
            await browser_monitor_interrupt(chat_id, request_id)
        except Exception:
            pass  # monitoring may simply not be active; interrupt is best-effort
    watch = _watch_command(text)
    if watch is not None and _live_pages.get(chat_id):
        return await _monitor_voice_turn(
            db, session, current_user, session_uuid, chat_id, watch,
            request_id, message_count)

    # 1. Held proposals / slot-fill values resolve before intent classification.
    pending = _get_pending(chat_id)
    if pending is not None:
        # While the loop is waiting for a FIELD VALUE, the text is data, not a
        # command: only an exact cancel phrase may cancel. A substring check
        # ate real values live ("Street light not working..." contains "no").
        # For held submit/navigate proposals the looser check stays: "no,
        # cancel that" must cancel a held click.
        is_fill_value = pending.get("kind") == "fill_next"
        if (not is_fill_value and _is_cancel(text)) or \
                (is_fill_value and _is_exact_cancel(text)):
            _pending.pop(chat_id, None)
            return await _browser_answer(
                db, session, current_user, session_uuid,
                "Cancelled — nothing was clicked or submitted. The page is still open if you want to continue.",
                pending.get("intent_label", "browser_act"),
                "user cancelled the held proposal",
                pending.get("confidence", 0.9), message_count)
        kind = pending.get("kind")
        if kind in ("submit", "navigate") and _is_confirm(text):
            return await _execute_confirmation(
                db, session, current_user, session_uuid, chat_id, pending,
                request_id, message_count)
        if kind == "fill_next":
            return await _fill_next_value(
                db, session, current_user, session_uuid, chat_id, pending,
                text, request_id, message_count)
        # Anything else: keep the proposal (TTL bounds staleness) and answer
        # this turn normally - interrupting with a question must not silently
        # arm a later "yes".
        # (falls through to URL/intent handling below)

    # 2. A user-supplied URL opens (or re-points) the live session. This is the
    # only opener: RAG output and guesses can never open pages.
    url = _extract_url(text, request.screen_context)
    if url is not None and _live_pages.get(chat_id) != url:
        try:
            opened = await _ensure_live_session(chat_id, url, request_id)
        except HTTPException as e:
            return await _browser_answer(
                db, session, current_user, session_uuid,
                f"I couldn't open that page: {e.detail}",
                "browser_inspect", f"live session open failed: {e.detail}",
                0.9, message_count)
        except Exception as e:
            # Any transport failure reaching the browser service must surface
            # as an honest answer here - letting it propagate would trip the
            # get_db yield-wrapper and misreport a browser outage as a 503
            # database failure (found live: "Database connection failed: All
            # connection attempts failed" for a browser-agent outage).
            return await _browser_answer(
                db, session, current_user, session_uuid,
                f"My browsing service is unreachable right now: {describe(e)}. "
                "I can still answer from knowledge - try asking without a link.",
                "browser_inspect", "browser service unreachable",
                0.9, message_count)
        if isinstance(opened, dict) and opened.get("status") == "needs_confirmation":
            _pending[chat_id] = {
                "kind": "navigate", "proposal": opened["proposal"], "url": url,
                "intent_label": "browser_inspect", "confidence": 0.9,
                "created_at": time.time(),
            }
            return await _finish_turn(
                db, session, current_user, session_uuid,
                answer=(opened["proposal"]["summary"]
                        + " Reply 'yes, open it' to proceed, or 'cancel'."),
                agent_used="browser_agent", suggested_action="confirm_navigate",
                sources_used=[], confidence=0.9,
                intent_label="browser_inspect",
                reasoning="sensitive domain held for confirmation",
                message_count=message_count)
        # A data: URL is kilobytes of payload: it opened the session, but the
        # intent classifier only needs the marker, not the payload. Shrink it
        # in place (also keeps message meta small); the live page is what the
        # browser_* path reads, not this string.
        if url.startswith("data:") and request.screen_context and url in request.screen_context:
            title = opened.get("title", "embedded page") if isinstance(opened, dict) else "embedded page"
            request.screen_context = request.screen_context.replace(
                url, f"{title} (embedded page, live session open)")
        if len(url) > 1500 and url in text:
            # Same shrink for the message itself: intent caps input at 2000
            # chars, and a pasted data: page would 400 every query. The full
            # text is already saved on the user message above; classification
            # only needs the question + a marker.
            text = text.replace(url, "[embedded page, live session open]")
            request.input_text = text
        # The page is NOW open, so this same turn's question ("where is the
        # submit button?") must route to the live page, not to generic advice.
        # The classifier's browser routing keys on the "Live page:" marker;
        # the frontend sets it for page-context uploads, so set it here too
        # for the URL-in-message flow. (Extracted from the real page title.)
        title = opened.get("title", "") if isinstance(opened, dict) else ""
        marker = f"Live page: {title or 'open page'} ({url})."
        request.screen_context = (marker + " "
                                  + (request.screen_context or ""))
    return None


async def _execute_confirmation(db, session, current_user, session_uuid, chat_id,
                                pending, request_id, message_count) -> QueryResponse:
    """Run a held navigate/submit proposal exactly once (single-use ids)."""
    _pending.pop(chat_id, None)
    kind = pending.get("kind")
    try:
        if kind == "navigate":
            result = await browser_confirm(chat_id, pending["proposal"]["proposal_id"],
                                           request_id)
            _live_pages[chat_id] = pending.get("url", "")
            text = (f"Opened {result.get('title') or result.get('url')}. "
                    f"Ask me about anything on it.")
            action = "confirm_navigate"
        else:
            result = await browser_confirm(chat_id, pending["proposal"]["proposal_id"],
                                           request_id)
            after = result.get("page_title_after") or ""
            text = (f"Submitted — clicked '{result.get('label')}' on the live page."
                    + (f" The page now shows: {after}." if after else ""))
            action = "submitted"
    except Exception as e:
        code, detail = _browser_error_detail(e)
        if code == 404:
            text = "That confirmation already expired or was used. Nothing was submitted - tell me again what to do."
        else:
            text = f"Couldn't complete that: {detail}. Nothing was submitted."
        action = "none"
    return await _finish_turn(
        db, session, current_user, session_uuid,
        answer=text, agent_used="browser_agent", suggested_action=action,
        sources_used=[], confidence=pending.get("confidence", 0.9),
        intent_label=pending.get("intent_label", "browser_act"),
        reasoning="executed held user-confirmed proposal",
        message_count=message_count,
    )


async def _fill_next_value(db, session, current_user, session_uuid, chat_id,
                           pending, text: str, request_id,
                           message_count) -> QueryResponse:
    """One slot-fill turn: fill the current field, ask the next (or propose)."""
    if text.strip().lower() == "skip":
        remaining = pending.get("remaining", [])[1:]
        filled = pending.get("filled", [])
    else:
        current = (pending.get("remaining", []) or [{}])[0]
        try:
            result = await browser_act(
                chat_id, "fill", label=current.get("label"),
                selector=current.get("selector"), value=text, request_id=request_id)
        except Exception as e:
            code, detail = _browser_error_detail(e)
            if code == 404 and pending.get("url"):
                await _ensure_live_session(chat_id, pending["url"], request_id)
                result = await browser_act(
                    chat_id, "fill", label=current.get("label"),
                    selector=current.get("selector"), value=text, request_id=request_id)
            else:
                return await _browser_answer(
                    db, session, current_user, session_uuid,
                    f"I couldn't fill '{current.get('label')}': {detail}.",
                    "browser_act", "slot fill failed", 0.9, message_count)
        readback = (result.get("detail") or {}).get("readback", "")
        filled = pending.get("filled", []) + [
            {"label": current.get("label"), "value": readback or text}]
        remaining = pending.get("remaining", [])[1:]
    if remaining:
        _pending[chat_id] = {**pending, "remaining": remaining, "filled": filled,
                             "created_at": time.time()}
        nxt = remaining[0].get("label")
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"Got it: {filled[-1]['label']} = '{filled[-1]['value']}'. "
            f"What should go in '{nxt}'? (or say 'skip')",
            "browser_act", "slot fill in progress", 0.9, message_count)
    # All slots filled: locate the real submit control on the live page and
    # hold it - never guess a label, never click yet.
    summary_lines = "\n".join(f"- {item['label']}: '{item['value']}'" for item in filled)
    try:
        insp = await _with_reopen(
            chat_id, pending.get("url"), request_id,
            lambda: browser_inspect(chat_id, "submit book pay confirm", request_id))
    except Exception as e:
        _, detail = _browser_error_detail(e)
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"Fields are filled ({len(filled)}), but I couldn't re-read the page "
            f"to find its submit button: {detail}. Nothing was submitted.",
            "browser_act", "submit lookup failed", 0.9, message_count)
    cands = [m for m in (insp.get("matches") or []) if m.get("submit_action")]
    if not cands:
        seen = ", ".join(f"'{m.get('label')}'" for m in (insp.get("matches") or [])[:4])
        return await _browser_answer(
            db, session, current_user, session_uuid,
            f"Fields are filled ({len(filled)}), but I can't identify a submit "
            f"button on this page (I see: {seen or 'nothing matching'}). "
            "Nothing was submitted - tell me which control submits it.",
            "browser_act", "submit lookup failed", 0.9, message_count)
    top = cands[0]
    return await _hold_submit(
        db, session, current_user, session_uuid, chat_id,
        top.get("selector", ""), top.get("label", "submit"),
        f"I found the form and filled {len(filled)} fields:\n{summary_lines}",
        0.95, message_count, request_id)


async def _monitor_voice_turn(db, session, current_user, session_uuid, chat_id,
                              action: str, request_id,
                              message_count) -> QueryResponse:
    """'watch my screen' / 'stop watching my screen' through normal chat.
    The explicit consent action lands here for voice users; the button and
    keyboard shortcut land on /api/monitor/start|stop - same door."""
    from app.services.clients import browser_monitor_start, browser_monitor_stop
    if action == "start":
        try:
            result = await browser_monitor_start(chat_id, "voice", request_id)
        except Exception as e:
            code, detail = _browser_error_detail(e)
            if code == 409:
                text = ("I can't start watching yet: " + detail
                        + " Open a page first (paste its link), then say "
                          "'watch my screen' again.")
            else:
                text = f"I couldn't start watching the page: {detail}."
            return await _browser_answer(
                db, session, current_user, session_uuid, text,
                "monitor", "monitor start failed", 0.9, message_count)
        stats = (result.get("stats") or {}).get("counters", {})
        return await _finish_turn(
            db, session, current_user, session_uuid,
            answer=("Now watching the live page. I'll tell you when something "
                    "meaningful changes - a new error, a message, a page "
                    "loading. Say 'stop watching my screen', press Alt+W, or "
                    "use the Stop watching button to end it."),
            agent_used="browser_agent", suggested_action="monitor_started",
            sources_used=[], confidence=0.95,
            intent_label="monitor", reasoning="explicit user opt-in (voice)",
            message_count=message_count)
    # stop
    try:
        result = await browser_monitor_stop(chat_id, request_id)
        counters = (result.get("stats") or {}).get("counters", {})
        summary = (f" ({counters.get('narrations', 0)} narrations, "
                   f"{counters.get('nim_calls', 0)} vision calls)")
    except Exception:
        summary = ""  # already stopped / swept: the end state is what matters
    return await _finish_turn(
        db, session, current_user, session_uuid,
        answer=f"Stopped watching the page{summary}. Nothing further is "
               f"captured or sent.",
        agent_used="browser_agent", suggested_action="monitor_stopped",
        sources_used=[], confidence=0.95,
        intent_label="monitor", reasoning="user revoked consent (voice)",
        message_count=message_count)


async def require_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available in demo mode. Configure SUPABASE_DB_URL to enable.")
    return db


def _browser_error_detail(exc: Exception) -> tuple[int, str]:
    """Map browser-agent HTTP failures to (status, message) for honest answers:
    423/403/409/429 describe the situation (challenge, forbidden, no page,
    budget spent) - only 5xx/exceptions are upstream failures (502)."""
    import httpx
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            detail = ""
        code = exc.response.status_code
        if code in (409, 422, 423, 403, 429):
            return code, str(detail)[:300] or f"browser refused ({code})"
    return 502, f"Browser service error: {describe(exc)}"


async def _ensure_live_session(chat_id: str, url: str,
                               request_id: str | None) -> dict:
    """Open the chat session's live page (idempotent server-side), or relay a
    sensitive-domain confirmation proposal. Returns the browser-agent payload."""
    known = _live_pages.get(chat_id)
    if known is not None and known != url:
        # New explicit URL supersedes the old page for this chat.
        result = await browser_open_session(chat_id, url, request_id)
    elif known == url:
        result = {"status": "reused"}
    else:
        result = await browser_open_session(chat_id, url, request_id)
    if isinstance(result, dict) and result.get("status") != "needs_confirmation":
        _live_pages[chat_id] = url
    return result


async def _finish_turn(db: AsyncSession, session, current_user, session_uuid: UUID,
                       answer: str, agent_used: str, suggested_action: str | None,
                       sources_used: list, confidence: float,
                       intent_label: str, reasoning: str,
                       message_count: int) -> QueryResponse:
    """Shared tail: policy rewrite, persist both messages, respond."""
    result = await db.execute(select(Preference).where(Preference.user_id == current_user.id))
    prefs = result.scalar_one_or_none()

    clarifying_count = await count_clarifying_questions(db, session_uuid)

    sig_result = await db.execute(
        select(BehaviorSignal).where(BehaviorSignal.session_id == session_uuid)
    )
    signals = sig_result.scalar_one_or_none()

    adjusted_answer = await adjust_response(
        raw_answer=answer,
        user_prefs=prefs,
        clarifying_count=clarifying_count,
        session_context={
            "message_count": message_count,
            "replay_count": signals.replay_count if signals else 0,
            "skip_count": signals.skip_count if signals else 0,
        },
        db=db,
        session_id=session_uuid
    )

    assistant_msg = Message(
        session_id=session.id,
        role=MessageRole.assistant,
        content=adjusted_answer,
        agent_used=agent_used,
        meta={
            "intent": intent_label,
            "reasoning": reasoning,
            "sources_used": sources_used,
            "suggested_action": suggested_action,
            "clarifying_count": clarifying_count
        }
    )
    db.add(assistant_msg)
    await db.commit()

    return QueryResponse(
        response_text=adjusted_answer,
        agent_used=agent_used,
        suggested_action=suggested_action,
        confidence=confidence,
        sources_used=sources_used,
    )


@router.post("/query", response_model=QueryResponse)
async def process_query(
    http_request: Request,
    request: QueryRequest,
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    # REAL MODE: require live DB and live services - no mock fallback, real 503/404/502
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running (docker compose up postgres)")
    # Verify session belongs to user - REAL ownership check (rejects cross-user)
    session_uuid = parse_session_uuid(request.session_id)
    try:
        result = await db.execute(
            select(Session).where(Session.id == session_uuid, Session.user_id == current_user.id)
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found - create one via POST /api/session first")

    # Get recent history for context
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_messages = list(reversed(result.scalars().all()))
    history = [f"{m.role.value}: {m.content}" for m in recent_messages]

    # Save user message
    user_msg = Message(
        session_id=session.id,
        role=MessageRole.user,
        content=request.input_text,
        meta={"input_source": request.input_source, "screen_context": request.screen_context}
    )
    db.add(user_msg)

    # Step 0: live-browser turns (Round 8). Pending confirmations and slot-fill
    # values are resolved BEFORE intent classification: "submit" or "Asha
    # Sharma" must reach the held proposal, never the general agent.
    request_id = getattr(http_request.state, "request_id", None) or http_request.headers.get("X-Request-ID")
    browser_turn = await _maybe_browser_turn(
        db, session, current_user, session_uuid, request, request_id,
        message_count=len(recent_messages),
    )
    if browser_turn is not None:
        return browser_turn

    # Step 1: Call Intent & Context Engine - propagate X-Request-ID for tracing
    try:
        intent_result = await classify_intent(
            session_id=request.session_id,
            input_text=request.input_text,
            screen_context=request.screen_context,
            history=history,
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Intent service error: {describe(e)}")

    # Guardrail: the model may jump to browser_* with no page anywhere (no live
    # session, no URL in this turn). Demote deterministically to the
    # informational equivalent instead of failing or hallucinating a page.
    if intent_result.target_agent == "browser_agent":
        page_present = (
            _live_pages.get(request.session_id) is not None
            or _extract_url(request.input_text, request.screen_context) is not None
        )
        if not page_present:
            fallback = {
                "browser_inspect": ("web_navigation_help", "web_agent"),
                "browser_act": ("form_help", "form_agent"),
            }.get(intent_result.intent, ("web_navigation_help", "web_agent"))
            intent_result = IntentResponse(
                intent=fallback[0], target_agent=fallback[1],
                extracted_entity=intent_result.extracted_entity,
                reasoning=intent_result.reasoning + " [demoted: no live page open]",
                confidence=intent_result.confidence,
            )
        else:
            browser_turn = await _handle_browser_intent(
                db, session, current_user, session_uuid, request,
                intent_result, request_id, message_count=len(recent_messages),
            )
            if browser_turn is not None:
                return browser_turn

    # Step 2: Call appropriate Task Agent - propagate X-Request-ID
    try:
        agent_result = await get_agent_response(
            session_id=request.session_id,
            agent=intent_result.target_agent,
            query=request.input_text,
            entity=intent_result.extracted_entity,
            extra_context=request.screen_context or "",
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent service error: {describe(e)}")

    # Step 3+4: policy rewrite, persist, respond (shared with browser turns).
    # Confidence is what the intent classifier actually reported for this
    # classification (LLM self-assessment, or keyword-match strength on
    # fallback) - previously this was a hardcoded 0.85 for every answer.
    return await _finish_turn(
        db, session, current_user, session_uuid,
        answer=agent_result.answer,
        agent_used=intent_result.target_agent,
        suggested_action=agent_result.suggested_action,
        sources_used=agent_result.sources_used,
        confidence=intent_result.confidence,
        intent_label=intent_result.intent,
        reasoning=intent_result.reasoning,
        message_count=len(recent_messages),
    )


@router.post("/query-demo", response_model=QueryResponse)
async def process_query_demo(http_request: Request, request: QueryRequest):
    """
    REAL endpoint without DB: still calls live Intent & Agents services (no mocks).
    Used for demos when postgres not available; main /api/query is DB-persisted real mode.
    """
    request_id = getattr(http_request.state, "request_id", None) or http_request.headers.get("X-Request-ID")
    # Demo: create a simple in-memory history (no DB persistence, but services are live)
    history = []  # In production this would come from DB; here we keep it ephemeral

    # Step 1: Call Intent & Context Engine
    try:
        intent_result = await classify_intent(
            session_id=request.session_id,
            input_text=request.input_text,
            screen_context=request.screen_context,
            history=history,
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Intent service error: {describe(e)}")

    # Step 2: Call appropriate Task Agent
    try:
        agent_result = await get_agent_response(
            session_id=request.session_id,
            agent=intent_result.target_agent,
            query=request.input_text,
            entity=intent_result.extracted_entity,
            extra_context=request.screen_context or "",
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent service error: {describe(e)}")

    # Step 3: Apply Policy Engine (simplified - no DB prefs)
    from app.models.preference import VerbosityLevel, DisabilityProfile, LanguageComplexity
    from types import SimpleNamespace

    # Demo defaults: full shape so every policy rule sees the same attributes
    # as a real Preference row (a partial namespace 500'd on Rule 2 before).
    prefs = SimpleNamespace(
        verbosity_level=VerbosityLevel.standard,
        disability_profile=DisabilityProfile.none,
        language_complexity=LanguageComplexity.standard,
    )
    clarifying_count = 0
    
    adjusted_answer = await adjust_response(
        raw_answer=agent_result.answer,
        user_prefs=prefs,
        clarifying_count=clarifying_count,
        session_context={"message_count": 0},
        db=None,  # type: ignore
        session_id=request.session_id
    )

    return QueryResponse(
        response_text=adjusted_answer,
        agent_used=intent_result.target_agent,
        suggested_action=agent_result.suggested_action,
        confidence=intent_result.confidence,
        sources_used=agent_result.sources_used,
    )