"""Alternative formats: Braille shaping endpoint (Phase 4.3)."""
from fastapi import APIRouter, Query
from app.services.braille_formatter import to_braille_text, ascii_to_braille

router = APIRouter(prefix="/api/alt", tags=["alt"])


@router.get("/braille")
async def braille(text: str = Query(..., max_length=4000)):
    lines = to_braille_text(text)
    return {"lines": lines, "preview_braille": ascii_to_braille(text[:60])}
