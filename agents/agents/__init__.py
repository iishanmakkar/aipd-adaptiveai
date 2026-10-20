from .base import BaseAgent
from .form_agent import FormAgent
from .document_agent import DocumentAgent
from .web_agent import WebAgent
from .education_agent import EducationAgent
from .general_agent import GeneralAgent
from .ui_adjuster_agent import UIAdjusterAgent
from .content_explainer_agent import ContentExplainerAgent
from .profile_updater_agent import ProfileUpdaterAgent
from .navigation_agent import NavigationAgent
from .scheduler_agent import SchedulerAgent
from .translator_agent import TranslatorAgent
from .registry import AgentRegistry, agent_registry

__all__ = [
    "BaseAgent",
    "FormAgent",
    "DocumentAgent",
    "WebAgent",
    "EducationAgent",
    "GeneralAgent",
    "UIAdjusterAgent",
    "ContentExplainerAgent",
    "ProfileUpdaterAgent",
    "NavigationAgent",
    "SchedulerAgent",
    "TranslatorAgent",
    "AgentRegistry",
    "agent_registry",
]