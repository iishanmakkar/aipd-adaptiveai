"""Live page context: SEE a real web page (not generic advice).

POST /api/page-context loads the given public URL in a live headless Chromium
and returns what is ACTUALLY there: title, HTTP status, the interactive fields
with their real labels, and a vision-model description of the rendered page.
The chat UI attaches this as screen_context, so answers describe the real page
the user linked instead of reciting generic guidance.

SSRF-guarded (public http(s) only; file/internal/metadata refused with 422).
No DB, no auth: it reads a public page, like any browser would.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.form.browser_tool import BrowserTool
from app.api.url_guard import validate_browse_url

router = APIRouter(prefix="/api", tags=["page-context"])


class PageContextRequest(BaseModel):
    url: str = Field(..., min_length=1)


@router.post("/page-context")
async def page_context(req: PageContextRequest):
    try:
        validate_browse_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    browser = BrowserTool()
    try:
        await browser.start()
        try:
            nav = await browser.navigate(req.url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"page load failed: {type(e).__name__}: {str(e)[:150]}")
        await browser.wait_for_load()
        tree = await browser.get_accessibility_tree()
        fields = [
            {"label": n.get("label", ""), "type": n.get("role", ""),
             "required": bool(n.get("required", False))}
            for n in tree.get("tree", [])
            if n.get("label")
        ][:40]
        try:
            vlm = await browser.get_vlm_description(
                "Describe this web page for a visually impaired user: what site is it, "
                "what is its purpose, and what interactive elements (forms, buttons, "
                "links) are visible? Be concrete and specific.")
            description = vlm.get("description", "")
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)[:200])
        return {
            "url": nav["url"], "http_status": nav.get("http_status"),
            "title": await browser._page.title(),
            "field_count": len(fields), "fields": fields,
            "description": description,
        }
    finally:
        await browser.stop()
