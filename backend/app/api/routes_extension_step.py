"""POST /api/extension/step - the browser extension asks what to do next.

Structure in, one action out; see `app/services/step_planner.py` for what the
planner may and may not decide. This module owns the wire contract: what a
request is even allowed to contain, who may send it, and what happens when the
model is down.

The privacy boundary is enforced by the schema, not by convention. Every model
here is `extra="forbid"`, so a content-script bug (or a patched client) that
tries to post `value`, `selector`, `identity` or `bounds` gets a 422 naming the
field, instead of a server that quietly ignores the card number it just received.
Silently dropping a leaked value is still a leaked value.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.auth import get_current_user_optional
from app.services import step_planner
from app.services.step_planner import PlannerUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])

MAX_NODES = 400
MAX_LABELS = 60
MAX_HISTORY = 60


class StructureOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- value-shaped text must never reach here, and must be refused if it does ---

_PAN_LIKE = re.compile(r"\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}|\d{13,19}")
_SSN_LIKE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _luhn_valid(digits: str) -> bool:
    total, alternate = 0, False
    for char in reversed(digits):
        n = ord(char) - 48
        if alternate:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alternate = not alternate
    return total % 10 == 0


def value_shaped_text(text: str) -> Optional[str]:
    """Return what looked like a private value, or None.

    Only the page-derived strings are scanned: the user's own goal is theirs to
    say out loud, and refusing to read it back would not protect it. A card
    number in an accessible name means the client sent what it must not send.
    """
    if not text:
        return None
    for match in _SSN_LIKE.finditer(text):
        return f"ssn-shaped string {match.group(0)!r}"
    for match in _PAN_LIKE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 15 and _luhn_valid(digits):
            return f"card-number-shaped string ({len(digits)} digits, checksum-valid)"
    return None


def _clean_page_text(field_name: str, value: str) -> str:
    leak = value_shaped_text(value)
    if leak:
        raise ValueError(
            f"{field_name} contained a {leak}. /api/extension/step takes "
            "structure only - roles, accessible names, states, value kinds - and "
            "never a value the user typed. Check that redactSnapshot() ran before "
            "this request was sent."
        )
    return value


class SnapshotOption(StructureOnly):
    text: str = Field(default="", max_length=200)

    @field_validator("text")
    @classmethod
    def _no_values(cls, v: str) -> str:
        return _clean_page_text("select option label", v)


class SnapshotNode(StructureOnly):
    # The wire names are camelCase because that is what `ax.js describe()` and
    # `privacy.js redactNode()` produce. Renaming here would mean a client that
    # posts `nameSource` arriving as an unexpected extra - i.e. a 422 on a field
    # that is perfectly legal to send.
    ref: str = Field(..., min_length=1, max_length=64)
    tag: str = Field(default="", max_length=40)
    role: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=400)
    nameSource: str = Field(default="", max_length=60)
    unnamed: bool = False
    lowConfidenceName: bool = False
    interactive: bool = False
    kind: Optional[str] = Field(default=None, max_length=20)
    hasValue: bool = False
    sensitive: bool = False
    states: Dict[str, bool] = Field(default_factory=dict)
    inShadow: bool = False
    disabled: bool = False
    live: Optional[str] = Field(default=None, max_length=20)
    options: List[SnapshotOption] = Field(default_factory=list, max_length=40)

    @field_validator("name", "role", "tag")
    @classmethod
    def _no_values(cls, v: str) -> str:
        return _clean_page_text("accessible name", v)


class HistoryStep(StructureOnly):
    description: str = Field(default="", max_length=300)
    action: str = Field(default="", max_length=20)
    ref: str = Field(default="", max_length=64)
    status: str = Field(default="", max_length=32)
    change: str = Field(default="", max_length=300)
    error: str = Field(default="", max_length=200)

    @field_validator("description", "change")
    @classmethod
    def _no_values(cls, v: str) -> str:
        return _clean_page_text("step history", v)


class StepRequest(StructureOnly):
    goal: str = Field(..., min_length=1, max_length=2000)
    url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(default="", max_length=300)
    nodes: List[SnapshotNode] = Field(default_factory=list)
    available_labels: List[str] = Field(default_factory=list, max_length=MAX_LABELS)
    history: List[HistoryStep] = Field(default_factory=list, max_length=MAX_HISTORY)
    verbosity: Literal["blind_concise", "standard", "detailed"] = "standard"

    @field_validator("nodes")
    @classmethod
    def _bound_size(cls, v: List[SnapshotNode]) -> List[SnapshotNode]:
        if len(v) > MAX_NODES:
            raise ValueError(f"too many nodes: {len(v)} (cap is {MAX_NODES})")
        return v

    @field_validator("url", "title")
    @classmethod
    def _no_values(cls, v: str) -> str:
        return _clean_page_text("page metadata", v)


@router.post("/step")
async def extension_step(req: StepRequest, user=Depends(get_current_user_optional)):
    """Plan the next step of a spoken goal against a redacted page snapshot.

    Auth: `get_current_user_optional`, the same rule as the rest of the API - a
    forged or expired token is a 401 in every mode, and only a DEBUG boot gets the
    demo identity. Rate limiting is the heavy budget in app/main.py, because a
    task loop calls this once per step.
    """
    payload: Dict[str, Any] = {
        "goal": req.goal,
        "url": req.url,
        "title": req.title,
        "nodes": [n.model_dump() for n in req.nodes],
        "available_labels": req.available_labels,
        "history": [h.model_dump() for h in req.history],
        "verbosity": req.verbosity,
    }
    try:
        reply = await step_planner.plan_step(payload)
    except PlannerUnavailable as e:
        # A planner that is down says it is down. The extension narrates the
        # failure and stops; nothing here falls back to a keyword guess, because
        # "the model is unreachable" and "the model chose this button" cannot
        # share one status.
        logger.warning("extension step planner unavailable: %s", e)
        raise HTTPException(status_code=503,
                            detail=f"step planner unavailable: {str(e)[:200]}")
    except ValueError as e:
        logger.info("extension step reply unusable: %s", str(e)[:160])
        reply = {"status": "cannot", "action": None, "ref": None,
                 "value_from": "none", "value_label": None, "value_literal": None,
                 "expect": "none",
                 "narration": "The planner answered in a form I could not read, so I "
                              "did nothing.",
                 "confidence_source": "none", "why": str(e)[:200]}

    logger.info(json.dumps({
        "event": "extension_step",
        "user": str(getattr(user, "id", "")),
        "nodes": len(payload["nodes"]),
        "steps_done": len(payload["history"]),
        "status": reply["status"],
        "action": reply.get("action"),
        "expect": reply.get("expect"),
    }))
    return reply
