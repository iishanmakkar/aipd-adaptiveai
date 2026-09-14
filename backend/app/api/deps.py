"""Shared API helpers for the backend routers."""
from uuid import UUID

from fastapi import HTTPException


def describe(exc: Exception) -> str:
    """Render an upstream failure readably.

    httpx raises timeouts with an empty message, so `str(e)` alone produced
    'Agent service error: ' and left whoever debugged it with nothing.
    """
    message = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


def parse_session_uuid(raw: str) -> UUID:
    """Parse a session id from the wire.

    A malformed id is a client error (400). Letting it fall through to the
    database layer would report it as a 503 "database connection failed",
    which tells the caller to retry an input that will never succeed.
    """
    try:
        return UUID(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="session_id must be a valid UUID")
