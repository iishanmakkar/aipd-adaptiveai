from typing import Optional
from pydantic import BaseModel, Field

from app.models.preference import VerbosityLevel, DisabilityProfile, LanguageComplexity


class PreferenceUpdate(BaseModel):
    # All optional: a partial PUT changes one knob without resetting the
    # others (omitted fields used to fall back to defaults and silently wipe
    # an explicitly stored disability profile).
    verbosity_level: Optional[VerbosityLevel] = None
    voice_speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    disability_profile: Optional[DisabilityProfile] = None
    language_complexity: Optional[LanguageComplexity] = None


class PreferenceResponse(BaseModel):
    verbosity_level: VerbosityLevel
    voice_speed: float
    disability_profile: DisabilityProfile
    language_complexity: LanguageComplexity
