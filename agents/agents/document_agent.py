from .base import BaseAgent
from llm.prompts import DOCUMENT_AGENT_PROMPT
import re


def _w(q: str, w: str) -> bool:
    return re.search(r"\b" + re.escape(w) + r"\b", q) is not None


class DocumentAgent(BaseAgent):
    # The NO-DOCUMENT RULE in this agent's prompt requires a user-supplied
    # document; with empty context the pipeline must not feed it retrieved
    # helper docs to summarize instead.
    requires_document = True

    @property
    def agent_name(self) -> str:
        return "document_agent"

    @property
    def system_prompt_template(self) -> str:
        return DOCUMENT_AGENT_PROMPT

    def _get_suggested_action(self, query: str, entity: str) -> str:
        query_lower = query.lower()
        if any(_w(query_lower, w) for w in ["summarize", "summary", "overview"]):
            return "summarize_document"
        if any(_w(query_lower, w) for w in ["extract", "find", "locate", "where is"]):
            return "highlight_section"
        if any(_w(query_lower, w) for w in ["read", "read aloud", "speak"]):
            return "read_aloud"
        return "none"