from .base import BaseAgent
from .form_agent import FormAgent
from .document_agent import DocumentAgent
from .web_agent import WebAgent
from .education_agent import EducationAgent
from .general_agent import GeneralAgent
from .registry import AgentRegistry, agent_registry

__all__ = [
    "BaseAgent",
    "FormAgent",
    "DocumentAgent",
    "WebAgent",
    "EducationAgent",
    "GeneralAgent",
    "AgentRegistry",
    "agent_registry",
]