from .base import BaseAgent
from llm.prompts import FORM_AGENT_PROMPT
from rag.retriever import Retriever
from llm.client import LLMClient


class FormAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "form_agent"

    @property
    def system_prompt_template(self) -> str:
        return FORM_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if any(word in query_lower for word in ["where", "find", "locate", "which field"]):
            return "highlight_field"
        if any(word in query_lower for word in ["example", "sample", "format"]):
            return "show_example"
        return "none"