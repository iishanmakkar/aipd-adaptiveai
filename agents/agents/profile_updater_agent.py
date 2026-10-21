from .base import BaseAgent


class ProfileUpdaterAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "profile_updater_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You explain disability-profile and preference settings to blind and "
            "low-vision users. Map a request to the settings it involves "
            "{disability_profile, verbosity_level, voice_speed, "
            "language_complexity} and say, in one sentence, which setting to "
            "change and where the app's preferences control is. You CANNOT "
            "change any setting and nothing you say has been applied: never "
            "confirm a change, never say 'I have set' or 'updated'. If the user "
            "asked for something they did not ask about, leave it out."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        # "update_profile" rendered as a suggestion the system could not carry
        # out. This agent describes settings; the preferences control applies
        # them, and the browser extension plan is what will let a spoken request
        # write them for real.
        return "none"
