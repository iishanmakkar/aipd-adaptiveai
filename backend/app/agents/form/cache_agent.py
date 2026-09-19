"""Form Filler Cache Agent (Form Filler Agent, AWS Agentic Form Filling).

Caches discovered form field locations with ARIA snapshots and embeddings.
Enables deterministic replay on subsequent visits.
Per-site caching with semantic similarity search.
State filtering: find enabled buttons, available seats, etc.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from app.services.episodic_memory import EpisodicMemory, Episode, MemoryEntry, episodic_memory

logger = logging.getLogger(__name__)


class CacheAgent:
    """Caches form discoveries with embeddings for deterministic replay.
    
    Uses episodic memory service to store:
    - Initial ARIA tree snapshots
    - Field position/state embeddings
    - Successful action sequences
    - Per-site domain indexing
    """
    
    def __init__(self, memory: EpisodicMemory = None):
        self.memory = memory or episodic_memory
    
    async def cache_discovery(self, discovery: Dict[str, Any], task_type: str = "form_fill") -> str:
        """Cache a form discovery in episodic memory.
        
        Returns the episode ID for later replay.
        """
        # Extract field information
        fields = discovery.get("fields", [])
        url = discovery.get("url", "")
        
        # Generate ARIA snapshot b64 from tree
        tree_snapshot = discovery.get("tree_snapshot", [])
        aria_b64 = self._tree_to_b64(tree_snapshot)
        
        # Create episode
        episode = Episode(
            episode_id=discovery.get("discovery_id", hashlib.sha256(url.encode()).hexdigest()[:16]),
            task_type=task_type,
            aria_snapshot_b64=aria_b64,
            actions=self._actions_from_fields(fields),
            outcome="success",  # Discovery was successful
            pii_filtered=True,  # Fields are structural, not user data
            site_domain=self._get_domain(url),
            metadata={"url": url, "field_count": len(fields)},
        )
        
        # Store in memory
        episode_id = await self.memory.store_episode(episode)
        logger.info(f"Cached form discovery {episode_id} with {len(fields)} fields")
        return episode_id
    
    def _tree_to_b64(self, tree: List[Dict[str, Any]]) -> str:
        """Convert ARIA tree to base64 snapshot."""
        # Create a simplified JSON representation
        simplified = []
        for node in tree[:30]:  # First 30 nodes
            simplified.append({
                "tag": node.get("tag", ""),
                "role": node.get("role", ""),
                "label": node.get("label", "")[:50] if node.get("label") else "",
            })
        json_str = json_str = json.dumps(simplified, ensure_ascii=False)
        return base64.b64encode(json_str.encode()).decode()
    
    def _actions_from_fields(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert fields to action sequence for episode storage.

        Every action carries the REAL locating data observed in the DOM
        (css selector, label, placeholder) - replay uses these, never the
        internal field_id hash (which exists nowhere in the page).
        """
        actions = []
        for i, field in enumerate(fields):
            ftype = field["type"]
            if ftype in ("button", "submit", "radio", "checkbox"):
                atype = "click"
            elif ftype in ("combobox", "listbox", "select"):
                atype = "select"
            else:
                atype = "focus_and_type"
            action = {
                "type": atype,
                "field_id": field["field_id"],
                "selector": field.get("selector", ""),
                "label": field.get("label", ""),
                "placeholder": field.get("placeholder", ""),
                "description": field.get("description", ""),
                "status": "success",
                "order": i,
            }
            actions.append(action)
        return actions
    
    @staticmethod
    def _get_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc or url
        except Exception:
            return url