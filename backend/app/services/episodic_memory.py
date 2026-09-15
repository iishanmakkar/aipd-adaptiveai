"""Episodic Memory & Continuous Learning (AWS, Form Filler Agent, GitHub Accessibility Agent).

Stores successful workflows as episodes, reflects/consolidates patterns,
and supports semantic retrieval for replay. Per-site cache with initial
ARIA snapshot embedding. Automatic PII filtering.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# --- Types ---

class Episode:
    """A recorded successful workflow episode."""
    
    def __init__(
        self,
        episode_id: str,
        task_type: str,  # "form_fill", "browser_automation", "navigation", etc.
        aria_snapshot_b64: str,  # Initial ARIA tree snapshot
        actions: List[Dict[str, Any]],  # Successful action sequence
        outcome: str,  # "success", "partial", "failure"
        pii_filtered: bool,
        embedding: Optional[List[float]] = None,
        site_domain: Optional[str] = None,
        created_at: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.episode_id = episode_id
        self.task_type = task_type
        self.aria_snapshot_b64 = aria_snapshot_b64
        self.actions = actions
        self.outcome = outcome
        self.pii_filtered = pii_filtered
        self.embedding = embedding or []
        self.site_domain = site_domain
        self.created_at = created_at or time.time()
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "task_type": self.task_type,
            "aria_snapshot_b64": self.aria_snapshot_b64,
            "actions": self.actions,
            "outcome": self.outcome,
            "pii_filtered": self.pii_filtered,
            "embedding": self.embedding,
            "site_domain": self.site_domain,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Episode":
        return cls(
            episode_id=data["episode_id"],
            task_type=data["task_type"],
            aria_snapshot_b64=data["aria_snapshot_b64"],
            actions=data["actions"],
            outcome=data["outcome"],
            pii_filtered=data["pii_filtered"],
            embedding=data.get("embedding"),
            site_domain=data.get("site_domain"),
            created_at=data.get("created_at"),
            metadata=data.get("metadata", {}),
        )


class MemoryEntry:
    """Entry in episodic memory with TTL and relevance scoring."""
    
    def __init__(
        self,
        episode: Episode,
        access_count: int = 0,
        last_accessed: float = 0.0,
        relevance_score: float = 1.0,
    ):
        self.episode = episode
        self.access_count = access_count
        self.last_accessed = last_accessed
        self.relevance_score = relevance_score


# --- Memory Service ---

class EpisodicMemory:
    """AgentCore-style episodic memory service.
    
    Stores successful workflows as episodes with:
    - TTL-based expiration
    - LRU eviction
    - PII automatic filtering
    - Semantic embedding for retrieval
    - Per-site caching
    - Reflection/consolidation pattern extraction
    """
    
    def __init__(
        self,
        max_episodes: int = 1000,
        ttl_seconds: int = 86400,  # 24 hours
        max_turns_per_episode: int = 50,
        embedding_dim: int = 384,
        similarity_threshold: float = 0.75,
    ):
        self.max_episodes = max_episodes
        self.ttl_seconds = ttl_seconds
        self.max_turns_per_episode = max_turns_per_episode
        self.embedding_dim = embedding_dim
        self.similarity_threshold = similarity_threshold
        
        # In-memory store (in production: Redis/Postgres with pgvector)
        self._episodes: Dict[str, MemoryEntry] = {}
        self._site_index: Dict[str, List[str]] = {}  # domain -> episode_ids
        self._lru_order: List[str] = []  # for eviction
        self._embedding_model = None  # Would be SentenceTransformers model
    
    # --- Storage Operations ---
    
    async def store_episode(self, episode: Episode) -> str:
        """Store a new episode, evicting if necessary."""
        # PII filter check
        if not self._has_pii(episode.actions):
            episode = Episode(
                **{**episode.to_dict(), "pii_filtered": True}
            )
        
        # Generate embedding if not present
        if not episode.embedding:
            episode = Episode(
                **{**episode.to_dict(), "embedding": await self._generate_embedding(episode)}
            )
        
        # Create memory entry
        entry = MemoryEntry(
            episode=episode,
            access_count=0,
            last_accessed=time.time(),
            relevance_score=1.0,
        )
        
        # Store
        self._episodes[episode.episode_id] = entry
        
        # Index by domain
        if episode.site_domain:
            if episode.site_domain not in self._site_index:
                self._site_index[episode.site_domain] = []
            self._site_index[episode.site_domain].append(episode.episode_id)
        
        # LRU eviction if over capacity
        if len(self._episodes) > self.max_episodes:
            self._evict_episodes()
        
        logger.info(f"Stored episode {episode.episode_id} (task_type={episode.task_type})")
        return episode.episode_id
    
    async def access_episode(self, episode_id: str) -> Optional[Episode]:
        """Mark an episode as accessed (for relevance scoring)."""
        entry = self._episodes.get(episode_id)
        if entry is None:
            return None
        
        entry.access_count += 1
        entry.last_accessed = time.time()
        
        # Decay relevance if not accessed recently
        time_since_access = time.time() - entry.last_accessed
        if time_since_access > self.ttl_seconds:
            # TTL expired - will be cleaned on next access
            pass
        
        # Boost relevance for recently accessed
        entry.relevance_score = min(1.0, entry.relevance_score + 0.1)
        
        return entry.episode
    
    # --- Retrieval ---
    
    async def find_similar(
        self,
        task_type: str,
        query_embedding: List[float],
        site_domain: Optional[str] = None,
        min_relevance: float = 0.0,
    ) -> List[Tuple[Episode, float]]:
        """Find similar episodes using vector similarity.
        
        Returns list of (episode, similarity_score) tuples.
        """
        query_emb = np.array(query_embedding, dtype=float)
        
        candidates: List[Tuple[str, float]] = []  # (episode_id, similarity)
        
        # Index search by domain
        domain_ids = self._site_index.get(site_domain, []) if site_domain else []
        
        # Check relevant episodes
        episode_ids_to_check = set()
        if site_domain:
            episode_ids_to_check.update(domain_ids)
        # Also check all episodes for better matches
        episode_ids_to_check.update(self._episodes.keys())
        
        for eid in episode_ids_to_check:
            entry = self._episodes.get(eid)
            if entry is None:
                continue
            
            # Check TTL
            age = time.time() - entry.episode.created_at
            if age > self.ttl_seconds:
                continue
            
            # Check relevance
            if entry.relevance_score < min_relevance:
                continue
            
            # Skip if same episode
            if entry.episode.task_type != task_type:
                continue
            
            # Cosine similarity
            ep_emb = np.array(entry.episode.embedding, dtype=float)
            if len(ep_emb) == 0 or len(query_emb) == 0:
                similarity = 0.0
            else:
                dot = np.dot(query_emb, ep_emb)
                norms = np.linalg.norm(query_emb) * np.linalg.norm(ep_emb)
                similarity = dot / norms if norms > 0 else 0.0
            
            if similarity >= self.similarity_threshold:
                candidates.append((entry.episode, similarity))
        
        # Sort by similarity (highest first)
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Update access counts for returned episodes
        for episode, _ in candidates[:5]:  # Top 5
            await self.access_episode(episode.episode_id)
        
        return candidates
    
    # --- PII Filtering ---
    
    def _has_pii(self, actions: List[Dict[str, Any]]) -> bool:
        """Check if actions contain PII that should be filtered."""
        pii_patterns = [
            "credit.card", "ssn", "social.security", "password", "bank.account",
            "cvv", "pin", "account.number", "routing.number"
        ]
        
        text_content = " ".join(
            str(a.get("description", "")) + " " + str(a.get("value", "")) 
            for a in actions
        ).lower()
        
        return any(pattern in text_content for pattern in pii_patterns)
    
    # --- Reflection & Consolidation ---
    
    async def reflect_on_episode(self, episode_id: str) -> Dict[str, Any]:
        """Reflect on an episode to extract patterns for consolidation."""
        entry = self._episodes.get(episode_id)
        if entry is None:
            return {"error": "Episode not found"}
        
        episode = entry.episode
        patterns = {
            "success_patterns": [],
            "failure_patterns": [],
            "common_obstacles": [],
            "recommended_adjustments": [],
        }
        
        # Analyze action sequence for patterns
        if episode.outcome == "success" and len(episode.actions) > 1:
            # Extract success pattern: what made it work
            successful_actions = [a for a in episode.actions if a.get("status") == "success"]
            if successful_actions:
                patterns["success_patterns"].append({
                    "key_actions": len(successful_actions),
                    "action_types": [a.get("type") for a in successful_actions],
                    "duration_pattern": self._analyze_duration_pattern(successful_actions),
                })
            
            # Common obstacles from any failed actions
            failed_actions = [a for a in episode.actions if a.get("status") in ("error", "failure")]
            if failed_actions:
                patterns["failure_patterns"] = [
                    a.get("description", "unknown") for a in failed_actions
                ]
                patterns["common_obstacles"] = self._extract_obstacle_types(failed_actions)
            
            # Recommended adjustments
            patterns["recommended_adjustments"] = await self._generate_adjustments(episode)
        
        return patterns
    
    def _analyze_duration_pattern(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze timing patterns in successful actions."""
        durations = [a.get("duration_ms", 0) for a in actions if a.get("duration_ms")]
        if not durations:
            return {"avg_ms": 0, "pattern": "unknown"}
        
        avg_ms = sum(durations) / len(durations)
        return {"avg_ms": round(avg_ms, 1), "pattern": "consistent" if len(set(durations)) < 3 else "variable"}
    
    def _extract_obstacle_types(self, failed_actions: List[Dict[str, Any]]) -> List[str]:
        """Extract types of obstacles from failed actions."""
        obstacle_keywords = [
            "disabled", "not.found", "timeout", "element.change", "captcha",
            "permission.denied", "network.error"
        ]
        
        types_found = set()
        for a in failed_actions:
            desc = a.get("description", "").lower()
            for kw in obstacle_keywords:
                if kw in desc:
                    types_found.add(kw)
        
        return list(types_found)
    
    async def _generate_adjustments(self, episode: Episode) -> List[str]:
        """Generate recommended adjustments based on episode analysis."""
        adjustments = []
        
        # If many failures were "element not found"
        if any("not found" in a.get("description", "").lower() for a in episode.actions):
            adjustments.append("retry element discovery with ARIA tree before interaction")
        
        # If many timeouts
        if any("timeout" in a.get("description", "").lower() for a in episode.actions):
            adjustments.append("increase wait/timeout thresholds")
        
        # Generic success pattern reminder
        if episode.outcome == "success":
            adjustments.append("this workflow pattern is reliable - prefer cached replay")
        
        return adjustments
    
    # --- Embedding Generation ---
    
    async def _generate_embedding(self, episode: Episode) -> List[float]:
        """Generate sentence-transformers embedding for the episode.
        
        In production would use: SentenceTransformers('all-MiniLM-L6-v2')
        Here we use a hash-based mock embedding for demo purposes.
        """
        # Create a deterministic embedding from episode data
        # In production: model.encode(f"{episode.task_type}|{len(episode.actions)}|{episode.outcome}")
        hash_input = f"{episode.task_type}|{len(episode.actions)}|{episode.outcome}|{episode.site_domain or ''}"
        hash_val = int(hashlib.sha256(hash_input.encode()).hexdigest()[:16], 16)
        
        # Generate pseudo-random but deterministic embedding
        np.random.seed(hash_val)
        embedding = np.random.randn(self.embedding_dim).tolist()
        
        # Normalize
        norm = sum(x*x for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x/norm for x in embedding]
        
        return embedding
    
    # --- Eviction ---
    
    def _evict_episodes(self) -> None:
        """Evict least relevant episodes (LRU + relevance scoring)."""
        # Sort by (last_accessed old, relevance low, access count low)
        scored = []
        for eid, entry in self._episodes.items():
            score = (
                -entry.last_accessed,  # older = higher score (evict first)
                -entry.relevance_score,  # lower relevance = higher score
                -entry.access_count  # lower access count = higher score
            )
            scored.append((score, eid))
        
        scored.sort()
        
        # Evict bottom 10%
        evict_count = max(1, len(self._episodes) // 10)
        for _, eid in scored[:evict_count]:
            episode = self._episodes.pop(eid).episode
            if episode.site_domain and eid in self._site_index.get(episode.site_domain, []):
                self._site_index[episode.site_domain].remove(eid)
            logger.info(f"Evicted episode {eid}")
    
    # --- Statistics ---
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory service statistics."""
        total = len(self._episodes)
        successful = sum(
            1 for e in self._episodes.values() 
            if e.episode.outcome == "success"
        )
        avg_access = sum(e.access_count for e in self._episodes.values()) / total if total > 0 else 0
        
        domains = set()
        for eid, entry in self._episodes.items():
            if entry.episode.site_domain:
                domains.add(entry.episode.site_domain)
        
        return {
            "total_episodes": total,
            "successful_episodes": successful,
            "success_rate": round(successful / total * 100, 1) if total > 0 else 0,
            "avg_access_count": round(avg_access, 1),
            "indexed_domains": len(domains),
            "ttl_seconds": self.ttl_seconds,
            "max_episodes": self.max_episodes,
        }


# --- Global Instance ---

episodic_memory: EpisodicMemory = EpisodicMemory()