from pydantic import BaseModel, Field

from app.models.preference import VerbosityLevel


class PreferenceUpdate(BaseModel):
    verbosity_level: VerbosityLevel
    voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)


class PreferenceResponse(BaseModel):
    verbosity_level: VerbosityLevel
    voice_speed: float
