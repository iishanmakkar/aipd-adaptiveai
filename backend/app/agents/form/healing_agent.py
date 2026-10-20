"""Form Filler Healing Agent (Form Filler Agent, Fantoma).

Field-level repair when a cached replay breaks: relocate the fields whose stored
selector no longer resolves onto the live page, then replay again. Full
re-discovery is the fallback, not the first move.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.services.episodic_memory import EpisodicMemory, episodic_memory
from app.agents.form.cache_agent import CacheAgent

from app.agents.form.browser_tool import BrowserTool

logger = logging.getLogger(__name__)


class HealingAgent:
    """Repairs broken form replays against the live DOM."""
    
    def __init__(self, browser: Optional[BrowserTool] = None, memory: Optional[EpisodicMemory] = None):
        self.browser = browser or BrowserTool()
        self.memory = memory or episodic_memory
        self.cache_agent = CacheAgent(self.memory)
    
    async def heal_replay(self, episode_id: str, current_url: str) -> Dict[str, Any]:
        """Repair a cached episode against the LIVE page it is about to replay on.

        What "broken" means in practice: the site re-rendered, so the css
        selector recorded at discovery no longer resolves, while the field is
        still present under the same accessible label or placeholder. So the
        repair is a relocation, not a guess: read the rendered tree, match each
        unresolvable field to a live node by its label/placeholder words, and
        store that node's real selector. Every repair is verifiable afterwards by
        replaying again.

        Returns:
          - "repaired": at least one stale field was relocated onto a live node
          - "re_discovered": too little survived; a fresh discovery was cached
          - "failed": the page could not be read at all
        """
        episode = await self.memory.access_episode(episode_id)
        if episode is None:
            return {"status": "failed", "reason": "Episode not in memory", "action": "re_discover"}

        try:
            await self.browser.start()
            await self.browser.navigate(current_url)
            await self.browser.wait_for_load()
            tree = (await self.browser.get_accessibility_tree()).get("tree", [])
        except Exception as e:
            await self.browser.stop()
            return {"status": "failed", "reason": f"live page unreadable: {type(e).__name__}",
                    "action": "re_discover"}

        page = self.browser._page
        actions = [dict(a) for a in episode.actions]
        repairs: List[Dict[str, Any]] = []
        unresolved: List[int] = []

        for i, action in enumerate(actions):
            sel = action.get("selector") or ""
            if sel:
                try:
                    if await page.query_selector(sel):
                        continue
                except Exception:
                    # Selector syntax error = corrupt cache, not stale DOM.
                    logger.warning("heal: bad selector syntax for %s, marking corrupt",
                                   action.get("field_id"))
                    unresolved.append(i)
                    action["_corrupt"] = True
                    continue
            unresolved.append(i)

        if not unresolved:
            # Nothing is stale - the failure was elsewhere (missing value, a
            # disabled field, navigation). Do not burn VLM/Chromium.
            await self.browser.stop()
            return {"status": "no_repair_needed", "action": "supply_values",
                    "reason": "all selectors resolve; failure is values/disabled/nav"}

        relocated = 0
        # Nodes still addressed by a surviving action are off limits: two fields
        # must never end up mapped onto one control.
        claimed = {actions[i].get("selector") for i in range(len(actions))
                   if i not in unresolved and actions[i].get("selector")}
        for i in unresolved:
            action = actions[i]
            if action.pop("_corrupt", False):
                continue  # syntax-corrupt: never heal onto the wrong field
            match = self._relocate(action, tree, claimed)
            if match is None:
                continue
            try:
                if not await page.query_selector(match):
                    continue
            except Exception:
                continue
            repairs.append({
                "field_id": action.get("field_id", ""),
                "label": action.get("label", ""),
                "old_selector": action.get("selector", ""),
                "new_selector": match,
                "via": action.pop("_matched_via", "label"),
            })
            action["selector"] = match
            claimed.add(match)
            relocated += 1

        await self.browser.stop()

        if relocated:
            await self.memory.update_episode_actions(episode_id, actions)
            return {
                "status": "repaired",
                "action": "replay_continue",
                "episode_id": episode_id,
                "repaired_fields": relocated,
                "stale_fields": len(unresolved),
                "repairs": repairs,
            }

        return await self._re_discover(current_url)

    @staticmethod
    def _words(text: Any) -> set:
        # Unicode word split: Devanagari etc. are words, not delimiters.
        # Single digits survive ("Seat 1" vs "Seat 2"); other single chars drop.
        parts = re.split(r"[^\w]+", str(text or "").lower(), flags=re.UNICODE)
        return {w for w in parts if len(w) > 1 or w.isdigit()}

    def _relocate(self, action: Dict[str, Any], tree: List[Dict[str, Any]],
                  taken: set) -> Optional[str]:
        """Find the live node that is the cached field, by label then
        placeholder word overlap. Returns its real selector, or None."""
        for source in ("label", "placeholder"):
            want = self._words(action.get(source))
            if not want:
                continue
            match = self._match_words(want, action.get("type"), tree, taken)
            if match is not None:
                action["_matched_via"] = source
                return match
        return None

    def _match_words(self, want: set, role: Any,
                     tree: List[Dict[str, Any]], taken: set) -> Optional[str]:
        # A cached click/select is a specific control class: never relocate a
        # "click Sleeper" radio onto the textbox that happens to share its
        # label. Same guard for focus_and_type — without it a "Full name"
        # textbox re-rendered as a link ("Enter your full name") scored 1.0
        # and the replay filled (or clicked) the wrong element.
        allowed_roles = {
            "select": ("combobox", "listbox"),
            "click": ("radio", "checkbox", "button", "switch"),
            "focus_and_type": ("textbox", "searchbox", "textarea", "combobox",
                               "search", "listbox"),
        }.get(role)
        best, best_score, tied = None, 0.0, False
        for node in tree:
            selector = node.get("selector")
            if not selector or selector in taken:
                continue
            if allowed_roles and node.get("role") not in allowed_roles:
                continue
            have = self._words(node.get("label")) | self._words(node.get("placeholder"))
            if not have:
                continue
            inter = len(want & have)
            union = len(want | have)
            score = inter / union if union else 0.0
            if score > best_score:
                best, best_score, tied = selector, score, False
            elif score == best_score and score > 0 and selector != best:
                tied = True
        if tied:
            return None  # ambiguous (two "Yes" radios): never guess blind
        return best if best_score >= 0.5 else None

    async def _re_discover(self, current_url: str) -> Dict[str, Any]:
        """Repair is not possible - map the page again and cache that episode."""
        from app.agents.form.discovery_agent import DiscoveryAgent

        discovery = await DiscoveryAgent(self.browser).discover_form(current_url)
        if not discovery.get("fields"):
            return {"status": "failed", "reason": "re-discover found no fields",
                    "action": "no_repair", "fields_found": 0}
        new_episode_id = await self.cache_agent.cache_discovery(discovery, "form_fill")
        return {
            "status": "re_discovered",
            "new_episode_id": new_episode_id,
            "action": "re_discover_and_replay",
            "fields_found": len(discovery.get("fields", [])),
        }