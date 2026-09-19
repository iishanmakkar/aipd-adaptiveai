import asyncio
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
        # 1. Retrieve relevant documents.
        #    Embedding inference is CPU-bound sync work; running it on the event
        #    loop serialises every concurrent request, so offload it to a thread.
        #    The live page/screen context (if any) joins the retrieval query:
        #    without it, a generic question like "what does this form ask for?"
        #    retrieves whatever the words match (e.g. a declaration-form doc)
        #    instead of what is ACTUALLY on the user's page.
        retrieval_query = query if not extra_context else f"{query}\n{extra_context}"
        docs = await asyncio.to_thread(self.retriever.retrieve, retrieval_query)

        # 2. Format sources for prompt
        sources_text = self.retriever.format_sources(docs)
        source_ids = self.retriever.get_source_ids(docs)

        # 3. Build prompt
        prompt = self._build_prompt(query, entity, extra_context, sources_text)

        # 4. Call LLM (blocking HTTP client) - same reason as above
        messages = [
            {"role": "system", "content": self.system_prompt_template},
            {"role": "user", "content": prompt}
        ]
        answer = await asyncio.to_thread(self.llm.chat, messages)
        
        # 5. Determine suggested action
        suggested_action = self._get_suggested_action(query, entity)
        
        return {
            "answer": answer,
            "sources_used": source_ids,
            "suggested_action": suggested_action
        }

    def _build_prompt(self, query: str, entity: str, extra_context: str, sources_text: str) -> str:
        grounding = ""
        if extra_context:
            grounding = (
                "\nGROUNDING PRIORITY: the Extra Context above describes the ACTUAL "
                "page the user is on right now. Ground specifics (names, fields, "
                "elements, steps) in it FIRST; use Retrieved Knowledge only for "
                "background explanations of those specifics.")
        return f"""Entity: {entity}
Extra Context: {extra_context if extra_context else 'None provided'}
User Question: {query}

Retrieved Knowledge:
{sources_text}{grounding}"""

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "none"