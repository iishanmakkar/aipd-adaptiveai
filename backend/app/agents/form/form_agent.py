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
        failed_episode_id: Optional[str] = None
        if replay:
            result = await self._try_replay(url, user_values)
            # "partial_success" from a replay still means fields on the page were
            # not operated on - that is a broken cache, not a good enough answer.
            broke = (result.get("status") in ("failed", "partial_failure")
                     or result.get("failure_count", 0) > 0)
            if result.get("status") in ("success", "partial_success") and not broke:
                return result

            # Replay broke. The usual cause is the site re-rendering its markup:
            # the fields are still there under the same labels, only the stored
            # selectors are stale. Heal those in place and replay again before
            # paying for a full re-discovery.
            episode_id = result.get("episode_id")
            if episode_id and broke:
                healed = await self.heal_form(episode_id, url)
                if healed.get("status") in ("repaired", "re_discovered"):
                    target = healed.get("new_episode_id") or episode_id
                    retried = await self.replay_agent.replay_form(target, url, user_values)
                    if retried.get("status") == "success" and not retried.get("failure_count") and not retried.get("unfilled"):
                        return {
                            "status": retried["status"],
                            "episode_id": target,
                            "url": url,
                            "replay_results": retried.get("replay_results", []),
                            "success_count": retried.get("success_count", 0),
                            "failure_count": retried.get("failure_count", 0),
                            "unfilled": retried.get("unfilled", []),
                            "page_message": retried.get("page_message", ""),
                            "healed": healed,
                            "action": "form_filled_after_heal",
                        }
                    # The retried replay failed too: the healed selectors were
                    # wrong (or the page moved on). Remember the episode so the
                    # fresh discovery below replaces it instead of leaving the
                    # corrupted episode winning exact-URL replay until TTL.
                    failed_episode_id = episode_id

        # Discovery phase
        try:
            discovery = await self.discovery_agent.discover_form(url)
        except Exception as e:
            return {"status": "failed", "reason": f"discovery failed: {type(e).__name__}",
                    "episode_id": None, "url": url, "success_count": 0,
                    "failure_count": 0, "unfilled": [], "page_message": "",
                    "action": "discover_failed"}
        if any("captcha" in str(f.get("label", "")).casefold() or "recaptcha" in str(f.get("label", "")).casefold()
               for f in discovery.get("fields", [])):
            return {"status": "failed", "reason": "captcha challenge present: will not evade; sighted help needed",
                    "episode_id": None, "discovery_id": discovery.get("discovery_id"),
                    "url": url, "success_count": 0, "failure_count": 0,
                    "unfilled": [f.get("label") for f in discovery.get("fields", [])],
                    "page_message": "", "action": "captcha_refused"}
        if not discovery.get("fields"):
            # Honest empty: caching this would make every later replay
            # "succeed" with zero fills.
            return {
                "status": "no_fields",
                "episode_id": None,
                "discovery_id": discovery.get("discovery_id"),
                "url": url,
                "success_count": 0,
                "failure_count": 0,
                "unfilled": [],
                "page_message": discovery.get("vlm_description", ""),
                "action": "no_fillable_fields",
            }

        # Cache the discovery
        episode_id = await self.cache_agent.cache_discovery(discovery, "form_fill")
        if failed_episode_id and failed_episode_id != episode_id:
            try:
                await self.memory.delete_episode(failed_episode_id)
            except Exception:
                pass
        
        # Replay the form
        try:
            replay_result = await self.replay_agent.replay_form(episode_id, url, user_values)
        except Exception as e:
            return {"status": "failed", "reason": f"replay failed: {type(e).__name__}",
                    "episode_id": episode_id, "discovery_id": discovery.get("discovery_id"),
                    "url": url, "success_count": 0, "failure_count": 0,
                    "unfilled": [], "page_message": "", "action": "replay_failed"}
        
        # Combine results
        return {
            "status": replay_result.get("status", "failed"),
            "episode_id": episode_id,
            "discovery_id": discovery.get("discovery_id"),
            "url": url,
            "replay_results": replay_result.get("replay_results", []),
            "success_count": replay_result.get("success_count", 0),
            "failure_count": replay_result.get("failure_count", 0),
            "unfilled": replay_result.get("unfilled", []),
            "page_message": replay_result.get("page_message", ""),
            "action": "form_filled",
            "new_episode": replay_result.get("status", "") in ("failed", "expired"),
        }
    
    async def _try_replay(self, url: str, user_values: Dict[str, str] = None) -> Dict[str, Any]:
        """Replay the cached episode that actually corresponds to this page."""
        episode, _score = await self.memory.find_replay_candidate(
            task_type="form_fill",
            url=url,
            requested_fields=list(user_values or []),
        )
        if episode is None:
            return {"status": "no_cache", "reason": "No cached episodes found", "action": "discover"}

        result = await self.replay_agent.replay_form(episode.episode_id, url, user_values)
        # Carry the episode id through so a failed replay can be healed rather
        # than thrown away.
        result.setdefault("episode_id", episode.episode_id)
        return result
    
    async def heal_form(self, episode_id: str, current_url: str) -> Dict[str, Any]:
        """Attempt to heal a broken form replay.
        
        Used when replay fails during a session - attempts surgical repair
        before full re-discovery.
        """
        return await self.healing_agent.heal_replay(episode_id, current_url)