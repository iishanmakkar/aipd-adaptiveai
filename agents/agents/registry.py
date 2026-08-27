from typing import Dict
from .form_agent import FormAgent
from .document_agent import DocumentAgent
from .web_agent import WebAgent
from .education_agent import EducationAgent
from .general_agent import GeneralAgent
from rag.retriever import Retriever
from llm.client import LLMClient


class AgentRegistry:
    def __init__(self, retriever: Retriever, llm_client: LLMClient):
        self._agents: Dict[str, object] = {
            "form_agent": FormAgent(retriever, llm_client),
            "document_agent": DocumentAgent(retriever, llm_client),
            "web_agent": WebAgent(retriever, llm_client),
            "education_agent": EducationAgent(retriever, llm_client),
            "general_agent": GeneralAgent(retriever, llm_client),
        }

    def get(self, agent_name: str):
        return self._agents.get(agent_name)

    def get_all_names(self) -> list[str]:
        return list(self._agents.keys())


# Global instance (initialized in main.py)
agent_registry: AgentRegistry = None