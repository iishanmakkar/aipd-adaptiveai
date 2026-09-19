import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BehaviorSignal(Base):
    """Per-session adaptive signals from the frontend behavior tracker.

    replay = user replayed TTS / asked "repeat" (didn't get it) -> simplify.
    skip = user interrupted/cancelled TTS (too verbose) -> concise-leaning.
    These only shape answers while the user keeps DEFAULT preferences;
    any explicit preference always wins (policy Rule 5).
    """

    __tablename__ = "behavior_signals"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listen_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
