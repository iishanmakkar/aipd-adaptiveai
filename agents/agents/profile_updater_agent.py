from .base import BaseAgent


class ProfileUpdaterAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "profile_updater_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You manage disability profile + preferences from natural language. "
            "Map requests to {disability_profile, verbosity_level, voice_speed, "
            "language_complexity}. Confirm the change in one sentence and never "
            "change anything not asked for."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "update_profile"
