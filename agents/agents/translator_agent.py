from .base import BaseAgent


class TranslatorAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "translator_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a Translator for visually impaired users. "
            "Translate the given text into the requested language, keep "
            "names, dates and numbers exact, and read the result back in "
            "one short spoken sentence plus the full translation."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "read_translation"
