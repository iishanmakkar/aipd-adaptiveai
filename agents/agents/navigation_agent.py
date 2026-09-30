from .base import BaseAgent


class NavigationAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "navigation_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a Navigation guide for blind users. Given goals like "
            "'go to checkout' or 'find contact form', return step-by-step "
            "keyboard/screen-reader instructions grounded in the provided page "
            "context. Never click anything yourself."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "navigate"
