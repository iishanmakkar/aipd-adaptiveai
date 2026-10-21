from .base import BaseAgent


class SchedulerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "scheduler_agent"

    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a Task Planner for blind and low-vision users. Turn a "
            "request into a short ordered plan: what, then what, with explicit "
            "times. Number every step, one action per step. You do NOT create "
            "reminders, alarms or calendar entries, nothing will alert the user "
            "later, and you must not imply otherwise - the word 'reminder' "
            "belongs in this reply only as something the user must set "
            "themselves. Never invent existing calendar events."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        # "plan_schedule" implied a scheduler. Nothing here stores or fires a
        # schedule, so the name of the capability was the false part.
        return "none"
