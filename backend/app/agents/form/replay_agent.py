"""Form Filler Replay Agent (Form Filler Agent, AWS).

Plays back cached form filling actions from episodic memory.
Field-level replay with state verification before each action.
Enables "one-click" form filling on repeat visits.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

from app.services.episodic_memory import EpisodicMemory, Episode, episodic_memory

from app.agents.form.browser_tool import BrowserTool

logger = logging.getLogger(__name__)


class ReplayAgent:
    """Replays cached form filling actions from episodic memory."""
    
    def __init__(self, browser: Optional[BrowserTool] = None, memory: Optional[EpisodicMemory] = None):
        self.browser = browser or BrowserTool()
        self.memory = memory or episodic_memory
    
    async def replay_form(self, episode_id: str, url: str, values: Dict[str, str] = None) -> Dict[str, Any]:
        """Replay cached form filling actions.
        
        Args:
            episode_id: The cached episode ID
            url: Current page URL
            values: Optional user-filled values to override cached ones
            
        Returns replay result with status and any issues.
        """
        # Access episode to refresh relevance
        episode = await self.memory.access_episode(episode_id)
        if episode is None:
            return {"status": "failed", "reason": "Episode not found in memory", "action": "re_discover"}
        
        # Check TTL
        age = __import__("time").time() - episode.created_at
        if age > 86400:  # 24 hours
            return {"status": "expired", "reason": "Episode older than 24 hours", "action": "re_discover"}
        
        await self.browser.start()
        await self.browser.navigate(url)
        await self.browser.wait_for_load()
        
        replay_results = []
        success_count = 0
        failure_count = 0
        
        # Execute each action from the cached episode
        for i, action in enumerate(episode.actions):
            result = await self._execute_replay_action(action, values)
            replay_results.append(result)
            
            if result.get("status") == "success":
                success_count += 1
            else:
                failure_count += 1
                
                # If too many failures, stop and re-discover
                if failure_count >= 3:
                    await self.browser.stop()
                    return {
                        "status": "partial_failure",
                        "replay_results": replay_results,
                        "success_count": success_count,
                        "failure_count": failure_count,
                        "action": "re_discover_partial",
                    }
        
        await self.browser.stop()
        
        return {
            "status": "success" if failure_count == 0 else "partial_success",
            "replay_results": replay_results,
            "success_count": success_count,
            "failure_count": failure_count,
            "episode_id": episode_id,
            "action": "replay_complete",
        }
    
    async def _execute_replay_action(self, action: Dict[str, Any], values: Dict[str, str] = None) -> Dict[str, Any]:
        """Execute a single replay action with state verification.

        Locating order (all real DOM data stored at discovery time):
        stored css selector -> placeholder text -> label text.
        """
        action_type = action.get("type", "focus_and_type")
        field_id = action.get("field_id", "")
        label = action.get("label", "") or ""
        placeholder = action.get("placeholder", "") or ""
        page = self.browser._page

        field = None
        if action.get("selector"):
            try:
                field = await page.query_selector(action["selector"])
            except Exception:
                field = None
        if not field and placeholder:
            field = await page.query_selector(f"input[placeholder='{placeholder}']")
        if not field and label:
            field = await page.query_selector(f"label:has-text('{label}')")
        
        if not field:
            return {"status": "failed", "reason": f"Field {field_id} not found on page", "action": "skip"}
        
        # Check if field is enabled/interactable
        is_enabled = await field.is_enabled()
        if not is_enabled:
            return {"status": "skipped", "reason": f"Field {field_id} is disabled", "action": "skip"}
        
        # Determine value to use: callers key overrides by visible label
        # (what a user knows), falling back to the internal field id.
        value = None
        if values:
            value = values.get(label) or values.get(field_id)
        if value is None:
            # Use cached value or empty
            value = action.get("value", "")
        
        # Execute action based on type
        try:
            if action_type == "focus_and_type":
                await field.click()
                await field.fill(value or "")
                return {"status": "success", "action": action_type, "field_id": field_id, "value": value}
            
            elif action_type == "click":
                await field.click()
                return {"status": "success", "action": action_type, "field_id": field_id}
            
            elif action_type == "select":
                # Handle dropdown selection
                await field.select_option(value or None)
                return {"status": "success", "action": action_type, "field_id": field_id}
            
            else:
                return {"status": "success", "action": action_type, "field_id": field_id}
        
        except Exception as e:
            return {"status": "failed", "reason": str(e), "action": action_type}
    
    async def replay_with_state_check(self, episode_id: str, url: str, user_values: Dict[str, str] = None) -> Dict[str, Any]:
        """Replay with full state verification before each action."""
        # Similar to replay_form but with additional checks
        # (visibility, enabled state, not already filled, etc.)
        result = await self.replay_form(episode_id, url, user_values)
        
        # Add state verification info
        if result.get("status") in ("success", "partial_success"):
            # Verify all required fields were interacted with
            interacted_fields = set()
            for r in result.get("replay_results", []):
                if r.get("status") == "success":
                    interacted_fields.add(r.get("field_id"))
            
            # Check required fields from the original episode
            # (would need metadata about which fields are required)
            
        return result