"""Alternative formats: Braille shaping + Grade-1 translation (Phase 4.3)."""
from fastapi import APIRouter, Query
from app.services.braille_formatter import to_braille_text, grade1_lines, ascii_to_braille

router = APIRouter(prefix="/api/alt", tags=["alt"])


@router.get("/braille")
async def braille(text: str = Query(..., max_length=4000)):
    # "lines" is shaped plain text for a refreshable display; "grade1" is the
    # real uncontracted Unicode braille of the same text. Callers must keep
    # the two labels distinct - grade1 is NOT Grade-2 contracted braille.
    lines = to_braille_text(text)
    return {
        "lines": lines,
        "grade1": grade1_lines(text),
        "preview_braille": ascii_to_braille(text[:60]),
    }
