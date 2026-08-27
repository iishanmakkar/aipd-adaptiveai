from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid


class SessionCreate(BaseModel):
    pass  # No input needed, just creates a new session


class SessionResponse(BaseModel):
    session_id: str
    created_at: datetime


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    agent_used: str | None = None
    created_at: datetime


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageResponse]
    total: int
    page: int
    page_size: int