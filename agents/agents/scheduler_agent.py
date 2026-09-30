from .base import BaseAgent


class SchedulerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "scheduler_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a Productivity Planner for blind and low-vision users. "
            "Turn requests into a short ordered plan: what, when, reminder. "
            "Keep steps numbered, times explicit, one action per step. "
            "Never invent existing calendar events."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        return "plan_schedule"
