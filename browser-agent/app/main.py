"""Browser-agent service (port 8003): REAL autonomous web navigation.

Every endpoint drives a live headless Chromium (Playwright) and reports what
actually happened. Nothing here is simulated.
"""
from contextlib import asynccontextmanager
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Monitor/session safety events (starts, narrations, rate blocks) are INFO:
# without this they vanish under uvicorn's WARNING root level, and the logs
# are the audit trail for what the watcher captured and when.
logging.basicConfig(level=logging.INFO)

from app.services.browser_agent import BrowserAgent
from app.services.monitor import MonitorLoop, PageMonitor
from app.services.sessions import (
    SessionManager, detect_captcha, is_sensitive_url, is_submit_text,
)
from app.tools.driver import Driver
from app.tools.url_guard import validate_browse_url

sessions = SessionManager()
_sweep_task = None
_monitor_task = None


async def _run_monitor_loop():
    await MonitorLoop(sessions.all_sessions).run()


class BrowseRequest(BaseModel):
    url: str = Field(..., min_length=1)


class FillField(BaseModel):
    selector: str
    value: str = ""


class FillRequest(BaseModel):
    url: str = Field(..., min_length=1)
    fields: List[FillField] = Field(default_factory=list)


class AgentBrowseRequest(BaseModel):
    session_id: str = Field(default="default")
    intent: str = Field(..., min_length=1)
    context: Dict[str, Any] = Field(default_factory=dict)


# ---- Live sessions (Round 8): one persistent Chromium page per chat session.

class SessionOpenRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    confirmed: bool = False


class SessionNavigateRequest(BaseModel):
    url: str = Field(..., min_length=1)
    confirmed: bool = False


class SessionInspectRequest(BaseModel):
    target: str = Field(..., min_length=1)


class SessionActRequest(BaseModel):
    kind: str = Field(..., description="fill|click|select")
    label: Optional[str] = None
    selector: Optional[str] = None
    value: str = ""
    confirmed: bool = False


class SessionConfirmRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)


def _session_or_404(session_id: str):
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404,
                            detail="no live session - open one with POST /session/open first")
    return session


def _request_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Request-ID")


async def _navigate_session(session, url: str, request_id: Optional[str]) -> Dict[str, Any]:
    """Shared navigate path: budgets, robots note, real navigation, logging."""
    if not session.nav_budget.check_and_spend():
        raise HTTPException(status_code=429,
                            detail="navigation budget exhausted for this session (30/hour)")
    try:
        nav = await session.driver.navigate(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"navigation failed: {e}")
    session.url = nav["url"]
    session.title = nav.get("title", "")
    session.touch()
    robots_ok, robots_reason = True, "no host to check"
    if url.startswith(("http://", "https://")):
        robots_ok, robots_reason = await sessions.robots.allowed(url)
    session.log("navigate", url=url, http_status=nav.get("http_status"),
                robots_ok=robots_ok, robots_reason=robots_reason,
                request_id=request_id)
    return {"status": "opened" if not session.url else "navigated",
            "url": session.url, "title": session.title,
            "http_status": nav.get("http_status"),
            "robots": robots_reason}


def _needs_nav_confirm(url: str, confirmed: bool) -> bool:
    return (not confirmed) and is_sensitive_url(url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sweep_task, _monitor_task
    import asyncio
    _sweep_task = asyncio.create_task(sessions.sweep_loop())
    _monitor_task = asyncio.create_task(_run_monitor_loop())
    yield
    for task in (_sweep_task, _monitor_task):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="AdaptiveAI Browser Agent",
              description="Real Playwright web navigation + form filling (no stubs).",
              version="0.2.0",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "browser-agent", "port": 8003}


@app.post("/browse")
async def browse(req: BrowseRequest):
    """Navigate a REAL browser to req.url; return live title/status/snapshot."""
    try:
        validate_browse_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    driver = Driver()
    await driver.start()
    try:
        try:
            nav = await driver.navigate(req.url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"navigation failed: {e}")
        snap = await driver.snapshot()
        shot = await driver.screenshot_b64()
        return {
            "url": nav["url"], "http_status": nav["http_status"], "title": nav["title"],
            "node_count": len(snap.get("nodes", [])),
            "nodes": snap.get("nodes", [])[:50],
            "screenshot_bytes": len(shot),
        }
    finally:
        await driver.stop()


@app.post("/fill")
async def fill(req: FillRequest):
    """Fill REAL fields on a live page; every result carries a same-page readback."""
    if not req.fields:
        raise HTTPException(status_code=422, detail="fields must not be empty")
    try:
        validate_browse_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    driver = Driver()
    await driver.start()
    try:
        try:
            nav = await driver.navigate(req.url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"navigation failed: {e}")
        results = [await driver.fill(f.selector, f.value) for f in req.fields]
        ok = sum(1 for r in results if r.get("status") == "completed")
        return {"url": nav["url"], "http_status": nav["http_status"],
                "filled": ok, "total": len(results), "results": results}
    finally:
        await driver.stop()


@app.post("/agent/browse")
async def agent_browse(req: AgentBrowseRequest):
    """Run the orchestrator (plan -> REAL tools -> narrated result)."""
    agent = BrowserAgent(session_id=req.session_id)
    try:
        return await agent.execute_task(req.intent, req.context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"browser task failed: {e}")


@app.post("/session/open")
async def session_open(req: SessionOpenRequest, request: Request):
    """Open (or reuse) the chat session's live page. Sensitive domains and all
    URLs still pass url_guard; sensitive ones additionally need confirmation."""
    if not req.session_id.strip():
        raise HTTPException(status_code=422, detail="session_id must not be empty")
    try:
        validate_browse_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    session = await sessions.open(req.session_id.strip())
    if _needs_nav_confirm(req.url, req.confirmed):
        prop = session.propose(
            "navigate",
            f"{req.url} looks like a login/payment page. Confirm explicitly before I open it.",
            {"url": req.url})
        session.log("navigate_proposed", url=req.url, reason="sensitive-domain",
                    request_id=_request_id(request))
        return {"status": "needs_confirmation", "proposal": prop,
                "session_id": session.session_id}
    async with session.lock:
        await session.driver.start()
        try:
            result = await _navigate_session(session, req.url, _request_id(request))
        except HTTPException:
            raise
        result["session_id"] = session.session_id
        return result


@app.post("/session/{session_id}/navigate")
async def session_navigate(session_id: str, req: SessionNavigateRequest,
                           request: Request):
    session = _session_or_404(session_id)
    try:
        validate_browse_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if _needs_nav_confirm(req.url, req.confirmed):
        prop = session.propose(
            "navigate",
            f"{req.url} looks like a login/payment page. Confirm explicitly before I open it.",
            {"url": req.url})
        session.log("navigate_proposed", url=req.url, reason="sensitive-domain",
                    request_id=_request_id(request))
        return {"status": "needs_confirmation", "proposal": prop,
                "session_id": session.session_id}
    async with session.lock:
        await session.driver.start()
        result = await _navigate_session(session, req.url, _request_id(request))
        result["session_id"] = session.session_id
        return result


@app.get("/session/{session_id}/snapshot")
async def session_snapshot(session_id: str):
    session = _session_or_404(session_id)
    async with session.lock:
        try:
            snap = await session.driver.snapshot()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"snapshot failed: {e}")
        session.touch()
        nodes = snap.get("nodes", [])[:100]
        return {"session_id": session_id, "url": session.url,
                "title": snap.get("title", ""), "node_count": len(nodes),
                "nodes": nodes}


@app.post("/session/{session_id}/inspect")
async def session_inspect(session_id: str, req: SessionInspectRequest):
    """Locate element(s) matching target text on the LIVE page and describe
    each with its real label, role, position and neighbours - the grounded
    answer to 'where is the submit button on this page'."""
    session = _session_or_404(session_id)
    if not session.url:
        raise HTTPException(status_code=409,
                            detail="live session has no page yet - navigate first")
    async with session.lock:
        try:
            snap = await session.driver.snapshot()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"snapshot failed: {e}")
        session.touch()
        nodes = [n for n in (snap.get("nodes", []) or []) if n.get("label")]
        wanted = [w for w in req.target.lower().split() if len(w) > 1]
        scored = []
        for i, node in enumerate(nodes):
            # Match against the label AND the element's role/tag: "where is
            # the submit button" must find the real submit button even when
            # its label reads "Book tickets" (its type IS submit).
            haystack = " ".join((
                str(node.get("label", "")), str(node.get("type", "")),
                str(node.get("tag", "")))).lower()
            hits = sum(1 for w in wanted if w in haystack)
            if hits:
                scored.append((hits, i, node))
        scored.sort(key=lambda t: (-t[0], t[1]))
        matches = []
        for _, i, node in scored[:5]:
            prev_label = str(nodes[i - 1].get("label", ""))[:80] if i > 0 else ""
            next_label = str(nodes[i + 1].get("label", ""))[:80] if i + 1 < len(nodes) else ""
            matches.append({
                "label": node.get("label", ""), "role": node.get("type", ""),
                "selector": node.get("selector", ""),
                "position": f"{i + 1} of {len(nodes)} interactive elements",
                "before": prev_label, "after": next_label,
                "submit_action": bool(is_submit_text(
                    str(node.get("label", "")),
                    str(node.get("tag", "")),
                    str(node.get("type", "")))),
            })
        session.log("inspect", target=req.target, matches=len(matches))
        return {"session_id": session_id, "url": session.url,
                "title": snap.get("title", ""), "target": req.target,
                "match_count": len(matches), "matches": matches}


def _resolve_target(nodes: List[Dict[str, Any]],
                    label: Optional[str], selector: Optional[str]):
    """Resolve an act target to exactly one node, or explain why not."""
    if selector:
        hit = next((n for n in nodes if n.get("selector") == selector), None)
        if hit is None:
            return None, f"no element matches selector {selector!r}"
        return hit, ""
    if not label:
        return None, "act needs a label or a selector"
    wanted = [w for w in label.lower().split() if len(w) > 1]
    scored = []
    for node in nodes:
        text = str(node.get("label", "")).lower()
        hits = sum(1 for w in wanted if w in text)
        if hits:
            scored.append((hits, node))
    if not scored:
        return None, f"no element on this page matches {label!r}"
    scored.sort(key=lambda t: -t[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        options = [str(n.get("label", ""))[:60] for _, n in scored[:3]]
        return None, f"{label!r} matches several elements {options} - say which one"
    return scored[0][1], ""


@app.post("/session/{session_id}/act")
async def session_act(session_id: str, req: SessionActRequest, request: Request):
    """Fill/click/select ONE element on the live page.

    Submit-class targets (submit/pay/confirm/book/delete...) are NEVER executed
    here: they come back as a proposal the user must confirm. CAPTCHA markers
    refuse the act outright. robots.txt is enforced for http(s) hosts.
    """
    if req.kind not in ("fill", "click", "select"):
        raise HTTPException(status_code=422, detail="kind must be fill|click|select")
    session = _session_or_404(session_id)
    if not session.url:
        raise HTTPException(status_code=409,
                            detail="live session has no page yet - navigate first")
    async with session.lock:
        try:
            snap = await session.driver.snapshot()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"snapshot failed: {e}")
        captcha = detect_captcha(snap)
        if captcha:
            session.log("act_refused", reason="captcha", marker=captcha,
                        request_id=_request_id(request))
            raise HTTPException(status_code=423, detail=(
                f"this page shows a bot challenge ({captcha}) - I will not try "
                "to evade it. If you complete the check yourself, ask me again."))
        nodes = [n for n in (snap.get("nodes", []) or []) if n.get("label")]
        node, problem = _resolve_target(nodes, req.label, req.selector)
        if node is None:
            raise HTTPException(status_code=422, detail=problem)
        label = str(node.get("label", ""))
        if is_submit_text(label, str(node.get("tag", "")), str(node.get("type", ""))):
            if not req.confirmed:
                prop = session.propose(
                    "submit",
                    f"Ready to activate {label!r} on {session.url}. "
                    "Say 'submit' to actually click it, or 'cancel'.",
                    {"selector": node.get("selector", ""), "label": label})
                session.touch()
                session.log("submit_proposed", label=label,
                            request_id=_request_id(request))
                return {"status": "needs_confirmation", "proposal": prop,
                        "session_id": session.session_id}
            if not session.submit_budget.check_and_spend():
                raise HTTPException(status_code=429, detail=(
                    "submit budget exhausted for this session (5/hour)"))
            allowed, reason = await sessions.robots.allowed(session.url)
            if not allowed:
                session.log("submit_refused", label=label, reason=reason,
                            request_id=_request_id(request))
                raise HTTPException(status_code=403, detail=reason)
            try:
                result = await session.driver.click(node.get("selector", ""))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"submit click failed: {e}")
            session.touch()
            session.log("submit_executed", label=label, url=session.url,
                        request_id=_request_id(request))
            return {"status": "submitted", "label": label,
                    "detail": result, "session_id": session.session_id}
        if session.url.startswith(("http://", "https://")):
            allowed, reason = await sessions.robots.allowed(session.url)
            if not allowed:
                session.log("act_refused", label=label, reason=reason,
                            request_id=_request_id(request))
                raise HTTPException(status_code=403, detail=reason)
        try:
            if req.kind in ("fill", "select"):
                result = await session.driver.fill(node.get("selector", ""), req.value)
            else:
                result = await session.driver.click(node.get("selector", ""))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"act failed: {e}")
        session.touch()
        session.log("act", kind=req.kind, label=label,
                    request_id=_request_id(request))
        return {"status": result.get("status", "completed"), "label": label,
                "detail": result, "session_id": session.session_id}


@app.post("/session/{session_id}/confirm")
async def session_confirm(session_id: str, req: SessionConfirmRequest,
                          request: Request):
    """Execute a held proposal (navigate or submit). Wrong/expired id: 404."""
    session = _session_or_404(session_id)
    async with session.lock:
        prop = session.take_proposal(req.proposal_id)
        if prop is None:
            raise HTTPException(status_code=404, detail=(
                "no matching pending proposal - it may have expired or been used"))
        if prop["kind"] == "navigate":
            await session.driver.start()
            try:
                result = await _navigate_session(
                    session, prop["payload"]["url"], _request_id(request))
            except HTTPException:
                raise
            result["session_id"] = session.session_id
            result["confirmed_proposal"] = prop["proposal_id"]
            return result
        if prop["kind"] == "submit":
            if not session.submit_budget.check_and_spend():
                raise HTTPException(status_code=429, detail=(
                    "submit budget exhausted for this session (5/hour)"))
            allowed, reason = await sessions.robots.allowed(session.url)
            if not allowed:
                session.log("submit_refused", label=prop["payload"].get("label"),
                            reason=reason, request_id=_request_id(request))
                raise HTTPException(status_code=403, detail=reason)
            try:
                snap = await session.driver.snapshot()
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"snapshot failed: {e}")
            captcha = detect_captcha(snap)
            if captcha:
                session.log("submit_refused", reason="captcha", marker=captcha,
                            request_id=_request_id(request))
                raise HTTPException(status_code=423,
                                    detail="bot challenge appeared - refusing to submit")
            try:
                result = await session.driver.click(prop["payload"].get("selector", ""))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"submit click failed: {e}")
            session.touch()
            session.log("submit_executed", label=prop["payload"].get("label"),
                        url=session.url, confirmed=True,
                        request_id=_request_id(request))
            try:
                after = await session.driver.snapshot()
                confirmation = str(after.get("title", ""))
            except Exception:
                confirmation = ""
            return {"status": "submitted", "label": prop["payload"].get("label"),
                    "detail": result, "page_title_after": confirmation,
                    "session_id": session.session_id}
        raise HTTPException(status_code=422,
                            detail=f"unknown proposal kind {prop['kind']!r}")


@app.get("/session/{session_id}/text")
async def session_text(session_id: str):
    """Read the live page's visible text (confirmation readback after submits)."""
    session = _session_or_404(session_id)
    async with session.lock:
        try:
            result = await session.driver.extract_text()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"text extract failed: {e}")
        session.touch()
        return {"session_id": session_id, "url": session.url,
                "text": (result.get("text") or "")[:4000]}


@app.post("/session/{session_id}/close")
async def session_close(session_id: str):
    if not await sessions.close(session_id, reason="explicit"):
        raise HTTPException(status_code=404, detail="no such live session")
    return {"status": "closed", "session_id": session_id}


@app.get("/session/{session_id}/status")
async def session_status(session_id: str):
    session = _session_or_404(session_id)
    return {
        "session_id": session_id, "url": session.url, "title": session.title,
        "created_at": session.created_at, "last_active": session.last_active,
        "has_pending": session.pending is not None,
        "pending_kind": (session.pending or {}).get("kind"),
        "navigations_used": session.nav_budget.used,
        "submits_used": session.submit_budget.used,
        "actions_logged": len(session.action_log),
    }


@app.get("/sessions")
async def list_sessions():
    return {"sessions": sessions.active_ids(), "total": len(sessions.active_ids())}


# ---- Round 9: real-time page monitoring on the live session's page.

class MonitorStartRequest(BaseModel):
    """Explicit opt-in. There is deliberately no default-on path: monitoring
    only starts when the user (voice command, button, or shortcut - all
    landing here via the backend) takes this action for this session."""
    requested_by: str = Field(default="user",
                              description="control used: voice|button|shortcut")


class NarrationsQuery(BaseModel):
    since: int = 0


def _monitor_or_404(session):
    if session.monitor is None or not session.monitor.enabled:
        raise HTTPException(status_code=409,
                            detail="monitoring is not active on this session")
    return session.monitor


@app.post("/session/{session_id}/monitor/start")
async def monitor_start(session_id: str, req: MonitorStartRequest,
                        request: Request):
    session = _session_or_404(session_id)
    if not session.url:
        raise HTTPException(status_code=409,
                            detail="open a page on this session before starting monitoring")
    async with session.lock:
        if session.monitor is not None and session.monitor.enabled:
            return {"status": "already_active", "session_id": session_id,
                    "stats": session.monitor.stats()}
        monitor = PageMonitor(session_id, session.driver)
        # Baseline NOW, synchronously: if the background loop's first poll is
        # ever delayed (loaded host), changes the user makes right after
        # consenting would otherwise be swallowed into a late baseline and
        # never narrated. After this call every later change is a real delta.
        try:
            await monitor.poll_once()
        except Exception:
            pass  # loop retries; a failed baseline is just an early baseline
        session.monitor = monitor
        session.log("monitor_start", requested_by=req.requested_by,
                    consent="explicit", request_id=_request_id(request))
    return {"status": "started", "session_id": session_id,
            "requested_by": req.requested_by, "stats": monitor.stats()}


@app.post("/session/{session_id}/monitor/stop")
async def monitor_stop(session_id: str, request: Request):
    session = _session_or_404(session_id)
    monitor = _monitor_or_404(session)
    async with session.lock:
        monitor.stop(reason="user-stop")
        session.log("monitor_stop", request_id=_request_id(request),
                    nim_calls_total=monitor.counters["nim_calls"])
    return {"status": "stopped", "session_id": session_id,
            "stats": monitor.stats()}


@app.post("/session/{session_id}/monitor/interrupt")
async def monitor_interrupt(session_id: str, request: Request):
    """User input just arrived: narrations hold for the quiet window so the
    assistant never talks over the user."""
    session = _session_or_404(session_id)
    monitor = _monitor_or_404(session)
    monitor.interrupt()
    return {"status": "interrupted", "session_id": session_id,
            "quiet_until": monitor.quiet_until}


@app.get("/session/{session_id}/monitor/status")
async def monitor_status(session_id: str):
    session = _session_or_404(session_id)
    if session.monitor is None:
        return {"session_id": session_id, "active": False}
    stats = session.monitor.stats()
    stats["active"] = stats.pop("enabled")
    return stats


@app.get("/session/{session_id}/monitor/narrations")
async def monitor_narrations(session_id: str, since: int = 0):
    """Pull new raw narrations (the backend policy-adapts + persists them,
    then the frontend speaks them). Delivered events are marked so they are
    not pulled twice; unsent events are discarded when the session closes."""
    session = _session_or_404(session_id)
    monitor = _monitor_or_404(session)
    events = monitor.narrations_since(since)
    if events:
        monitor.mark_delivered(events[-1]["id"])
    return {"session_id": session_id, "active": monitor.enabled,
            "events": events, "stats": monitor.stats()}
