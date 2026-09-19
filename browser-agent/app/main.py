"""Browser-agent service (port 8003): REAL autonomous web navigation.

Every endpoint drives a live headless Chromium (Playwright) and reports what
actually happened. Nothing here is simulated.
"""
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.services.browser_agent import BrowserAgent
from app.tools.driver import Driver
from app.tools.url_guard import validate_browse_url


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="AdaptiveAI Browser Agent",
              description="Real Playwright web navigation + form filling (no stubs).",
              version="0.1.0")
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
