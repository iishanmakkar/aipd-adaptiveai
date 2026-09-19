"""Form Filler Agent - Main orchestrator (Form Filler Agent, AWS Agentic Form Filling).

Discovery → Cache → Replay → Heal pipeline.
Combines all form filler capabilities into a single interface.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.services.episodic_memory import EpisodicMemory, episodic_memory
from app.agents.form.discovery_agent import DiscoveryAgent
from app.agents.form.cache_agent import CacheAgent
from app.agents.form.healing_agent import HealingAgent
from app.agents.form.replay_agent import ReplayAgent

from app.agents.form.browser_tool import BrowserTool


class FormAgent:
    """Main form filler agent orchestrating the full pipeline.
    
    Pipeline: DISCOVER → CACHE → REPLAY → HEAL
    
    Usage:
        agent = FormAgent(browser)
        # First time: discover and cache
        discovery = await agent.fill_form(url)
        # Subsequent times: replay from cache
        result = await agent.fill_form(url, replay=True)
    """
    
    def __init__(self, browser: Optional[BrowserTool] = None, memory: Optional[EpisodicMemory] = None):
        # A real headless Chromium is the default: this pipeline never runs on a
        # simulated browser. Pass an already-started driver to share one browser.
        self.browser = browser or BrowserTool()
        self.memory = memory or episodic_memory
        self.discovery_agent = DiscoveryAgent(self.browser)
        self.cache_agent = CacheAgent(self.memory)
        self.healing_agent = HealingAgent(self.browser, self.memory)
        self.replay_agent = ReplayAgent(self.browser, self.memory)
    
    async def fill_form(self, url: str, replay: bool = False, user_values: Dict[str, str] = None) -> Dict[str, Any]:
        """Fill a form, either by replaying cached actions or discovering anew.
        
        Args:
            url: Page URL containing the form
            replay: If True, try to replay cached form filling
            user_values: User-provided values to override cached ones
            
        Returns result with status, episode_id, and actions taken.
        """
        if replay:
            # Try replay first
            result = await self._try_replay(url, user_values)
            if result.get("status") in ("success", "partial_success"):
                return result
            # If replay failed, fall through to discovery
        
        # Discovery phase
        discovery = await self.discovery_agent.discover_form(url)
        
        # Cache the discovery
        episode_id = await self.cache_agent.cache_discovery(discovery, "form_fill")
        
        # Replay the form
        replay_result = await self.replay_agent.replay_form(episode_id, url, user_values)
        
        # Combine results
        return {
            "status": replay_result.get("status", "success"),
            "episode_id": episode_id,
            "discovery_id": discovery.get("discovery_id"),
            "url": url,
            "replay_results": replay_result.get("replay_results", []),
            "success_count": replay_result.get("success_count", 0),
            "failure_count": replay_result.get("failure_count", 0),
            "action": "form_filled",
            "new_episode": replay_result.get("status", "") in ("failed", "expired"),
        }
    
    async def _try_replay(self, url: str, user_values: Dict[str, str] = None) -> Dict[str, Any]:
        """Try to replay from cached episodes.
        
        Looks for the most relevant cached episode for this URL/task type.
        """
        # Find similar episodes for this URL/domain
        domain = self.cache_agent._get_domain(url)
        similar = await self.memory.find_similar(
            task_type="form_fill",
            query_embedding=[],  # Would use actual embedding in production
            site_domain=domain,
            min_relevance=0.5,
        )
        
        if not similar:
            return {"status": "no_cache", "reason": "No cached episodes found", "action": "discover"}
        
        # Use the most relevant episode
        best_episode, _ = similar[0]
        episode_id = best_episode.episode_id
        
        # Access to refresh relevance
        episode = await self.memory.access_episode(episode_id)
        if episode is None:
            return {"status": "no_cache", "reason": "Could not access episode", "action": "discover"}
        
        # Attempt replay
        return await self.replay_agent.replay_form(episode_id, url, user_values)
    
    async def heal_form(self, episode_id: str, current_url: str) -> Dict[str, Any]:
        """Attempt to heal a broken form replay.
        
        Used when replay fails during a session - attempts surgical repair
        before full re-discovery.
        """
        return await self.healing_agent.heal_replay(episode_id, current_url)