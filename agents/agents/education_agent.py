from .base import BaseAgent
from llm.prompts import EDUCATION_AGENT_PROMPT
import re


def _w(q: str, w: str) -> bool:
    return re.search(r"\b" + re.escape(w) + r"\b", q) is not None


class EducationAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "education_agent"

    @property
    def system_prompt_template(self) -> str:
        return EDUCATION_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if _w(query_lower, "example"):
            return "give_example"
        if any(word in query_lower for word in ["simplify", "simpler", "easier", "break down"]):
            return "simplify_further"
        if any(_w(query_lower, w) for w in ["practice", "exercise", "quiz", "test"]):
            return "suggest_practice"
        return "none"