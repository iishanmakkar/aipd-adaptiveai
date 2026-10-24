"""Main browser agent that orchestrates REAL tools for web navigation."""
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.tools.base import BrowserTool, AccessibilityTreeTool, VLMAnalysisTool, FormFillingTool
from app.tools.driver import Driver

# _plan_task returns this sentinel for any intent it does not actually
# implement, so execute_task can declare the run exploratory instead of
# narrating a fixed page sniff as a plan for what the user asked for.
EXPLORATORY = "exploratory"


class BrowserAgent:
    """Autonomous browser agent: one real Chromium per task, tools share it."""

    def __init__(self, session_id: str, preferences: Dict[str, Any] = None,
                 driver: Optional[Driver] = None):
        self.session_id = session_id
        self.preferences = preferences or {}
        self.driver = driver or Driver()
        self.tools = {
            "browser": BrowserTool(self.driver),
            "accessibility_tree": AccessibilityTreeTool(self.driver),
            "vlm_analysis": VLMAnalysisTool(self.driver),
            "form_filling": FormFillingTool(self.driver),
        }
        # Planning data only. A stored episode NEVER short-circuits execution:
        # replay must not report a step it did not run (see execute_task).
        self.episodic_memory: List[Dict[str, Any]] = []
        self.max_memory_entries = 50
        
    # These intents COMMIT on a live page. The session API holds them behind
    # consent, CAPTCHA checks, robots.txt, submit/nav budgets and the audit
    # log; this route has none of those gates, so executing them here was a
    # confirmation-free path to "Pay now" - one endpoint away from the
    # invariant the session API enforces. They are refused; the read-only
    # intents (extract_text, analyze_page, snapshot) stay.
    REFUSED_INTENTS = ("navigate_to_url", "click_element", "fill_field", "fill_form")

    async def execute_task(self, intent: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a full task on a REAL browser (started here, stopped after)."""
        if intent in self.REFUSED_INTENTS:
            return {
                "session_id": self.session_id,
                "intent": intent,
                "status": "refused",
                "unsupported_intent": True,
                "steps_completed": 0,
                "steps_failed": 0,
                "results": [],
                "narration": (
                    "I will not click, fill or navigate on this route: it has "
                    "no spending or consent gate. The session API "
                    "(/session/open, /session/{id}/navigate, /session/{id}/act) "
                    "carries those checks - use it for anything that acts."),
                "completed_at": datetime.utcnow().isoformat(),
            }
        # Parse intent and select tools
        steps = self._plan_task(intent, context or {})
        exploratory = steps is EXPLORATORY
        if exploratory:
            steps = [
                {"tool": "accessibility_tree", "action": "extract", "args": {}},
                {"tool": "browser", "action": "extract", "args": {}},
            ]

        results = []
        await self.driver.start()
        try:
            for step in steps:
                tool_name = step["tool"]
                action = step["action"]
                args = step.get("args", {})

                tool = self.tools.get(tool_name)
                if not tool:
                    results.append({"status": "error", "detail": f"Unknown tool: {tool_name}",
                                    "tool": tool_name, "action": action})
                    continue

                # Execute the tool (action is the first positional arg of every tool)
                try:
                    result = await tool.execute(action, **args)

                    # Store in episodic memory if successful
                    if result.get("status") == "completed":
                        self._store_episode(tool_name, action, args, result)

                    results.append(result)
                except Exception as e:
                    results.append({
                        "status": "error",
                        "detail": str(e),
                        "tool": tool_name,
                        "action": action
                    })
        finally:
            await self.driver.stop()

        # Consolidate results and return final status
        sniff_note = (
            "I looked the page over - structure and text only. I did not act, "
            "and this is not a booking. "
        ) if exploratory else ""
        return {
            "session_id": self.session_id,
            "intent": intent,
            "status": "exploratory" if exploratory else "planned",
            "unsupported_intent": exploratory,
            "steps_completed": len([r for r in results if r.get("status") == "completed"]),
            "steps_failed": len([r for r in results if r.get("status") == "error"]),
            "results": results,
            "narration": sniff_note + self._generate_narration(results),
            "completed_at": datetime.utcnow().isoformat()
        }
    
    def _plan_task(self, intent: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Plan tool steps for an intent. Every entry maps to an action the
        tools REALLY implement (see app/tools/base.py) - no aspirational verbs."""
        intent_tools = {
            "navigate_to_url": [{"tool": "browser", "action": "navigate",
                                 "args": {"url": context.get("url", "")}}],
            "click_element": [{"tool": "browser", "action": "click",
                               "args": {"selector": context.get("selector")}}],
            "fill_field": [{"tool": "form_filling", "action": "fill",
                            "args": {"field": context.get("field"), "value": context.get("value")}}],
            "extract_text": [{"tool": "browser", "action": "extract", "args": {}}],
            "analyze_page": [{"tool": "vlm_analysis", "action": "describe", "args": {}}],
            "snapshot": [{"tool": "accessibility_tree", "action": "extract", "args": {}}],
            "fill_form": [{"tool": "form_filling", "action": "discover_and_fill",
                           "args": {"fields": context.get("fields", [])}}],
        }
        
        # Default: try to match intent or declare the run exploratory
        if intent in intent_tools:
            return intent_tools[intent]

        # No natural-language understanding lives here: this map matches literal
        # verb keys, so anything else gets the fixed sniff and must SAY so. Real
        # step-by-step planning arrives with the extension's
        # POST /api/extension/step (design spec 4.2); until then claiming a plan
        # for "book me two seats" would be the exact fake this repo is removing.
        # The sniff deliberately excludes vlm_analysis, which hard-fails without
        # an API key and turned a clean "I only looked" into an error step.
        return EXPLORATORY
    
    def _store_episode(self, tool_name: str, action: str, args: dict, result: dict):
        """Store a successful workflow episode in episodic memory."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": self.session_id,
            "tool": tool_name,
            "action": action,
            "args_summary": self._summarize_args(args),
            "result": result,
        }
        
        self.episodic_memory.append(entry)
        if len(self.episodic_memory) > self.max_memory_entries:
            self.episodic_memory = self.episodic_memory[-self.max_memory_entries:]

    def _summarize_args(self, args: dict) -> str:
        """Summarize arguments for storage."""
        # Keep only non-sensitive keys
        safe_keys = {k: v for k, v in args.items() if not any(s in k.lower() for s in ["password", "token", "secret", "ssn", "credit"])}
        return str(safe_keys)[:100] if safe_keys else ""
    
    def _generate_narration(self, results: List[Dict[str, Any]]) -> str:
        """Generate human-readable narration of actions taken."""
        narration_parts = []
        for r in results:
            if r.get("status") == "completed":
                part = f"Completed: {r.get('action', 'action')}"
                if "details" in r:
                    part += f" ({r['details']})"
                narration_parts.append(part)
            elif r.get("status") == "error":
                part = f"Failed: {r.get('detail', 'unknown error')}"
                narration_parts.append(part)
        return " | ".join(narration_parts) if narration_parts else "No actions completed"