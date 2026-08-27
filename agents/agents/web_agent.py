from .base import BaseAgent
from llm.prompts import WEB_AGENT_PROMPT
from rag.retriever import Retriever
from llm.client import LLMClient


class WebAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "web_agent"

    @property
    def system_prompt_template(self) -> str:
        return WEB_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if any(word in query_lower for word in ["click", "press", "activate", "submit"]):
            return "highlight_button"
        if any(word in query_lower for word in ["navigate", "go to", "move to", "find"]):
            return "navigate_to"
        if any(word in query_lower for word in ["read", "what does it say"]):
            return "read_element"
        return "none"