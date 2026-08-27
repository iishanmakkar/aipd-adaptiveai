import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, String, ForeignKey, func, JSON, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base

if TYPE_CHECKING:
    from app.models.session import Session


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[MessageRole] = mapped_column(SQLEnum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    agent_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship(back_populates="messages")