from .base import BaseAgent


class UIAdjusterAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "ui_adjuster_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a UI Adjuster for visually impaired users. "
            "Given a natural-language UI goal (contrast, font, layout, focus), "
            "return a concise adjustment plan as JSON-friendly steps plus a "
            "one-sentence spoken summary. Never invent DOM ids."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "adjust_ui"
