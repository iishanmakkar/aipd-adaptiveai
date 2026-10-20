from .base import BaseAgent
from llm.prompts import WEB_AGENT_PROMPT
import re


def _w(q: str, w: str) -> bool:
    return re.search(r"\b" + re.escape(w) + r"\b", q) is not None


class WebAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "web_agent"

    @property
    def system_prompt_template(self) -> str:
        return WEB_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if any(_w(query_lower, w) for w in ["click", "press", "activate", "submit"]):
            return "highlight_button"
        if any(_w(query_lower, w) for w in ["navigate", "go to", "move to", "find"]):
            return "navigate_to"
        if any(_w(query_lower, w) for w in ["read", "what does it say"]):
            return "read_element"
        return "none"