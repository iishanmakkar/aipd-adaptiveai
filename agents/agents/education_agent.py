from .base import BaseAgent
from llm.prompts import EDUCATION_AGENT_PROMPT
from rag.retriever import Retriever
from llm.client import LLMClient


class EducationAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "education_agent"

    @property
    def system_prompt_template(self) -> str:
        return EDUCATION_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if any(word in query_lower for word in ["example", "example of", "instance"]):
            return "give_example"
        if any(word in query_lower for word in ["simplify", "simpler", "easier", "break down"]):
            return "simplify_further"
        if any(word in query_lower for word in ["practice", "exercise", "quiz", "test"]):
            return "suggest_practice"
        return "none"