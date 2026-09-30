from .base import BaseAgent


class ContentExplainerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "content_explainer_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a Content Explainer for blind and low-vision users. "
            "Explain screen content in simple language: numbered steps, no "
            "'click here', no visual-only references. Max 2 clauses per sentence."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "explain_content"
