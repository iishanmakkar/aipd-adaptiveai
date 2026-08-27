import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class VerbosityLevel(str, enum.Enum):
    concise = "concise"
    standard = "standard"
    detailed = "detailed"


class Preference(Base):
    __tablename__ = "preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    verbosity_level: Mapped[VerbosityLevel] = mapped_column(SQLEnum(VerbosityLevel), default=VerbosityLevel.standard, nullable=False)
    voice_speed: Mapped[float] = mapped_column(default=1.0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="preferences")