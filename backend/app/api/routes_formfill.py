"""Autonomous form filling (demo: book tickets and all).

POST /api/form-fill runs the REAL Discovery -> Cache -> Replay pipeline in a
live headless Chromium against the given URL with the given values. No DB is
needed; nothing is simulated - a fill result reports per-action status from the
live page, and failures name the cause.
"""
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.form.form_agent import FormAgent

router = APIRouter(prefix="/api", tags=["form-fill"])

_ALLOWED_SCHEMES = ("http://", "https://", "file://", "data:")


class FormFillRequest(BaseModel):
    url: str = Field(..., min_length=1)
    values: Dict[str, str] = Field(default_factory=dict)
    replay: bool = False


@router.post("/form-fill")
async def form_fill(req: FormFillRequest):
    if not req.url.startswith(_ALLOWED_SCHEMES):
        raise HTTPException(status_code=422, detail="url must be http(s), file or data")
    if not req.values:
        raise HTTPException(status_code=422, detail="values must not be empty")
    try:
        agent = FormAgent()
        return await agent.fill_form(req.url, replay=req.replay, user_values=req.values)
    except RuntimeError as e:
        # Honest configuration errors (no browser, no VLM key): 503, not 500.
        raise HTTPException(status_code=503, detail=str(e)[:300])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"form fill failed: {type(e).__name__}: {str(e)[:200]}")
