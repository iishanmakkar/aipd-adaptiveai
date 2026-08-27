from .base import BaseAgent
from llm.prompts import GENERAL_AGENT_PROMPT
from rag.retriever import Retriever
from llm.client import LLMClient


class GeneralAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "general_agent"

    @property
    def system_prompt_template(self) -> str:
        return GENERAL_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "none"