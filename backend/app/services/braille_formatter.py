"""Phase 4.3 — Braille display formatting.

Maps assistant text into a structured, Braille-friendly shape:
short lines, numbered steps preserved, visual-only phrases stripped.
Callers feed the result to a real display via brlapi; this module owns
only the text shaping (no hardware dependency).
"""
from __future__ import annotations

import re

_VISUAL_ONLY = [
    (re.compile(r"\bclick here\b", re.I), "activate the next button"),
    (re.compile(r"\bas shown\b[^.]*\.?", re.I), "."),
    (re.compile(r"\bsee (the )?(image|picture|screenshot)\b[^.]*\.?", re.I), "."),
]

# Grade-1-literary subset for key terms (full translation needs liblouis).
_GRADE1 = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑",
    "f": "⠋", "g": "⠛", "h": "⠓", "i": "⠊", "j": "⠚",
    "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝", "o": "⠕",
    "p": "⠏", "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞",
    "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭", "y": "⠽",
    "z": "⠵", " ": " ",
}


def to_braille_text(text: str, max_line: int = 40) -> list[str]:
    cleaned = text.strip()
    for pattern, replacement in _VISUAL_ONLY:
        cleaned = pattern.sub(replacement, cleaned)
    words = cleaned.split()
    # A 40-cell display cannot show a longer line: chunk overlong words
    # (pasted URLs, compound tokens) instead of leaking them through whole.
    chunks: list[str] = []
    for word in words:
        while len(word) > max_line:
            chunks.append(word[:max_line])
            word = word[max_line:]
        chunks.append(word)
    lines: list[str] = []
    current: list[str] = []
    width = 0
    for word in chunks:
        if width + len(word) + (1 if current else 0) > max_line:
            lines.append(" ".join(current))
            current, width = [word], len(word)
        else:
            current.append(word)
            width += len(word) + 1
    if current:
        lines.append(" ".join(current))
    return lines


def ascii_to_braille(text: str) -> str:
    return "".join(_GRADE1.get(ch.lower(), ch) for ch in text[:200])
