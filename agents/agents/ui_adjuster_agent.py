from .base import BaseAgent


class UIAdjusterAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "ui_adjuster_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a UI Adjuster for visually impaired users. Given a "
            "natural-language UI goal (contrast, font, layout, focus), return a "
            "concise adjustment plan as JSON-friendly steps plus a one-sentence "
            "spoken summary. You propose only: you cannot reach the page, and no "
            "setting, style or layout has been changed by this reply - say that "
            "if the user implies otherwise. Never invent DOM ids."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        # "adjust_ui" promised an adjustment that nothing performed. Applying
        # contrast, font and focus changes for real is the extension's page
        # adapter (design spec 8 item 5), not this prompt.
        return "none"
