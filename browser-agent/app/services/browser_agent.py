"""Main browser agent that orchestrates REAL tools for web navigation."""
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.tools.base import BrowserTool, AccessibilityTreeTool, VLMAnalysisTool, FormFillingTool
from app.tools.driver import Driver


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
        # Episodic memory: store successful workflows for replay
        self.episodic_memory: List[Dict[str, Any]] = []
        self.max_memory_entries = 50
        self.pattern_cache: Dict[str, Dict[str, Any]] = {}
        
    async def execute_task(self, intent: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a full task on a REAL browser (started here, stopped after)."""
        # Parse intent and select tools
        steps = self._plan_task(intent, context or {})

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

                # Check pattern cache first
                cache_key = f"{self.session_id}:{tool_name}:{action}"
                if cache_key in self.pattern_cache:
                    result = self.pattern_cache[cache_key].copy()
                    result["cached"] = True
                    results.append(result)
                    continue

                # Execute the tool (action is the first positional arg of every tool)
                try:
                    result = await tool.execute(action, **args)
                    result["cached"] = False

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
        return {
            "session_id": self.session_id,
            "intent": intent,
            "steps_completed": len([r for r in results if r.get("status") == "completed"]),
            "steps_failed": len([r for r in results if r.get("status") == "error"]),
            "results": results,
            "narration": self._generate_narration(results),
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
        
        # Default: try to match intent or return exploratory steps
        if intent in intent_tools:
            return intent_tools[intent]
        
        # Fallback: exploratory sequence
        return [
            {"tool": "accessibility_tree", "action": "extract", "args": {}},
            {"tool": "vlm_analysis", "action": "describe", "args": {}},
            {"tool": "browser", "action": "extract", "args": {}},  # Get page HTML/snapshot
        ]
    
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
        
        # Also cache for quick replay
        cache_key = f"{self.session_id}:{tool_name}:{action}"
        self.pattern_cache[cache_key] = {
            "args": args,
            "result": result,
            "stored_at": datetime.utcnow().isoformat()
        }
    
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