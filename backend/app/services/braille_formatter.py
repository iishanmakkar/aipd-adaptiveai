"""Phase 4.3 — Braille display formatting.

Two real transformations, both honestly labeled by callers:

1. ``to_braille_text`` — text shaping for a refreshable braille display:
   short lines, numbered steps preserved, visual-only phrases stripped.
   A brlapi-style display accepts plain text; this owns the shaping.
2. ``grade1_lines`` — a genuine Grade-1 (uncontracted) Unicode braille
   translation: letters, capital sign, digits via the number sign, and
   common punctuation. Grade 1 is a real, complete encoding for these
   characters — what it deliberately is NOT is Grade 2 contraction, and
   callers must not present it as anything more.
"""
from __future__ import annotations

import re

_VISUAL_ONLY = [
    (re.compile(r"\bclick here\b", re.I), "activate the next button"),
    (re.compile(r"\bas shown\b[^.]*\.?", re.I), "."),
    (re.compile(r"\bsee (the )?(image|picture|screenshot)\b[^.]*\.?", re.I), "."),
]

# Grade-1 letter cells (UNESCO standard dot patterns).
_LETTERS = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑",
    "f": "⠋", "g": "⠛", "h": "⠓", "i": "⠊", "j": "⠚",
    "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝", "o": "⠕",
    "p": "⠏", "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞",
    "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭", "y": "⠽",
    "z": "⠵",
}

# Digits reuse the first ten letter cells, switched in by the number sign.
_DIGITS = {
    "1": "⠁", "2": "⠃", "3": "⠉", "4": "⠙", "5": "⠑",
    "6": "⠋", "7": "⠛", "8": "⠓", "9": "⠊", "0": "⠚",
}

_PUNCTUATION = {
    ".": "⠲", ",": "⠂", "?": "⠦", "!": "⠮", "'": "⠄",
    '"': "⠐⠦", ":": "⠱", ";": "⠆", "-": "⠤", "(": "⠐⠣",
    ")": "⠐⠜", "/": "⠸⠌", "@": "⠈⠁", "&": "⠈⠯", "*": "⠈⠔",
    # In Grade 1, "#" IS the number sign (⠼): mapping it to number-sign + the
    # "0" cell doubled the sign and made a following digit run add a second
    # one ("#3" -> ⠼⠚⠼⠉ instead of ⠼⠉).
    "+": "⠐⠖", "=": "⠐⠶", "#": "⠼", "%": "⠸⠔", "$": "⠈⠙",
}

_CAPITAL_SIGN = "⠠"
_NUMBER_SIGN = "⠼"


def to_braille_text(text: str, max_line: int = 40) -> list[str]:
    if max_line <= 0:
        raise ValueError("max_line must be positive")
    # ponytail: preserve blank-line separated blocks (numbered steps stay steps)
    out: list[str] = []
    for para in text.strip().split("\n"):
        para = para.strip()
        if not para:
            continue
        cleaned = para
        for pattern, replacement in _VISUAL_ONLY:
            cleaned = pattern.sub(replacement, cleaned)
        cleaned = re.sub(r"\s*\.\s*\.\s*", ". ", cleaned)
        cleaned = re.sub(r"^[.\s]+", "", cleaned)
        words = cleaned.split()
        # A 40-cell display cannot show a longer line: chunk overlong words
        # (pasted URLs, compound tokens) instead of leaking them through whole.
        chunks: list[str] = []
        for word in words:
            while len(word) > max_line:
                chunks.append(word[:max_line])
                word = word[max_line:]
            chunks.append(word)
        current: list[str] = []
        width = 0
        for word in chunks:
            if width + len(word) + (1 if current else 0) > max_line:
                out.append(" ".join(current))
                current, width = [word], len(word)
            else:
                current.append(word)
                width += len(word) + 1
        if current:
            out.append(" ".join(current))
    return out


def grade1_word(word: str) -> str:
    """Translate one word (or token) to Grade-1 Unicode braille.

    Every uppercase letter is preceded by the capital sign; a run of digits
    is preceded by one number sign. Characters with no mapping pass through
    unchanged rather than being dropped, so nothing silently disappears.
    """
    cells: list[str] = []
    in_number = False
    for ch in word:
        if ch.isalpha() and ch.lower() in _LETTERS:
            in_number = False
            if ch.isupper():
                cells.append(_CAPITAL_SIGN)
            cells.append(_LETTERS[ch.lower()])
        elif ch.isdigit() and ch in _DIGITS:
            if not in_number:
                cells.append(_NUMBER_SIGN)
                in_number = True
            cells.append(_DIGITS[ch])
        else:
            in_number = False
            cells.append(_PUNCTUATION.get(ch, ch))
    return "".join(cells)


def grade1_lines(text: str, max_line: int = 40) -> list[str]:
    """Grade-1 braille of ``text``, wrapped to ``max_line`` cells per line.

    Wrapping counts braille cells (the translated length), not source
    characters — the number of cells is what a display shows.
    """
    braille_words: list[str] = []
    for word in text.split():
        bw = grade1_word(word)
        while len(bw) > max_line:
            braille_words.append(bw[:max_line])
            bw = bw[max_line:]
        braille_words.append(bw)
    lines: list[str] = []
    current: list[str] = []
    width = 0
    for word in braille_words:
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
    """Single-line Grade-1 preview (kept for the API preview field)."""
    return " ".join(grade1_word(word) for word in text.split()[:40])
