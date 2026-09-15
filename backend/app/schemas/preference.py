from pydantic import BaseModel, Field

from app.models.preference import VerbosityLevel, DisabilityProfile, LanguageComplexity


class PreferenceUpdate(BaseModel):
    verbosity_level: VerbosityLevel
    voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    disability_profile: DisabilityProfile = DisabilityProfile.none
    language_complexity: LanguageComplexity = LanguageComplexity.standard


class PreferenceResponse(BaseModel):
    verbosity_level: VerbosityLevel
    voice_speed: float
    disability_profile: DisabilityProfile
    language_complexity: LanguageComplexity
