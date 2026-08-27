from abc import ABC, abstractmethod
from typing import List, Dict
from rag.retriever import Retriever
from llm.client import LLMClient
from llm.prompts import GENERAL_AGENT_PROMPT


class BaseAgent(ABC):
    def __init__(self, retriever: Retriever, llm_client: LLMClient):
        self.retriever = retriever
        self.llm = llm_client

    @property
    @abstractmethod
    def agent_name(self) -> str:
        pass

    @property
    @abstractmethod
    def system_prompt_template(self) -> str:
        pass

    async def handle(self, query: str, entity: str, extra_context: str) -> dict:
        # 1. Retrieve relevant documents
        docs = self.retriever.retrieve(query)
        
        # 2. Format sources for prompt
        sources_text = self.retriever.format_sources(docs)
        source_ids = self.retriever.get_source_ids(docs)
        
        # 3. Build prompt
        prompt = self._build_prompt(query, entity, extra_context, sources_text)
        
        # 4. Call LLM
        messages = [
            {"role": "system", "content": self.system_prompt_template},
            {"role": "user", "content": prompt}
        ]
        answer = self.llm.chat(messages)
        
        # 5. Determine suggested action
        suggested_action = self._get_suggested_action(query, entity)
        
        return {
            "answer": answer,
            "sources_used": source_ids,
            "suggested_action": suggested_action
        }

    def _build_prompt(self, query: str, entity: str, extra_context: str, sources_text: str) -> str:
        return f"""Entity: {entity}
Extra Context: {extra_context if extra_context else 'None provided'}
User Question: {query}

Retrieved Knowledge:
{sources_text}"""

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "none"