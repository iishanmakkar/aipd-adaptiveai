from .base import BaseAgent
from llm.prompts import DOCUMENT_AGENT_PROMPT
from rag.retriever import Retriever
from llm.client import LLMClient


class DocumentAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "document_agent"

    @property
    def system_prompt_template(self) -> str:
        return DOCUMENT_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if any(word in query_lower for word in ["summarize", "summary", "overview"]):
            return "summarize_document"
        if any(word in query_lower for word in ["extract", "find", "locate", "where is"]):
            return "highlight_section"
        if any(word in query_lower for word in ["read", "read aloud", "speak"]):
            return "read_aloud"
        return "none"