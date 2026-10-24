"""Episodic Memory & Continuous Learning (AWS, Form Filler Agent, GitHub Accessibility Agent).

Stores successful workflows as episodes, reflects/consolidates patterns,
and supports semantic retrieval for replay. Per-site cache with initial
ARIA snapshot embedding. Automatic PII filtering.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple

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


# --- Field-identity embedding ---

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def _words(text: Any) -> List[str]:
    """Lowercased word tokens of one field-identity string."""
    return [w for w in _WORD_SPLIT.split(str(text or "").lower()) if len(w) > 1]


def _selector_words(selector: Any) -> List[str]:
    """Identity part of a css selector: '#pnr' / 'input#pnr' -> 'pnr'. Tag names
    and structural noise are dropped so a re-rendered page still matches."""
    return _words(re.sub(r"[.#:>\[\]\"'=|()\s]+", " ", str(selector or "")))


def episode_field_tokens(actions: List[Dict[str, Any]]) -> List[str]:
    """Words that identify the FIELDS of a form - never the values typed into
    them, so an episode's vector carries no user data."""
    tokens: List[str] = []
    for action in actions or []:
        tokens += _words(action.get("label"))
        tokens += _words(action.get("placeholder"))
        tokens += _selector_words(action.get("selector"))
    return tokens


def embed_tokens(tokens: List[str], dim: int = 384) -> List[float]:
    """Signed feature hashing (the 'hashing trick'): each distinct token is
    placed in one of `dim` buckets with a hash-derived sign, then L2-normalised.

    This is the whole trick behind replay matching, and it is why no model or
    API call is needed to answer 'is this the form we already mapped?': the
    same form yields identical token sets, so cosine ~1.0; a different form on
    the same host yields little overlap. Dependency-free on purpose - the
    backend image has no torch, and a browser-side assistant must not need one.
    """
    vec = [0.0] * dim
    for token in set(tokens):
        digest = hashlib.sha256(token.encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        vec[bucket] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


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
        # PII filter check: episodes whose actions carry PII are the ones that
        # get stamped pii_filtered (the inverted check labeled clean episodes
        # as filtered and stored PII-bearing ones as clean).
        if self._has_pii(episode.actions):
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
        
        # Index by domain (deduplicated: re-storing an id must not leave a
        # stale twin behind for eviction to trip over later).
        if episode.site_domain:
            if episode.site_domain not in self._site_index:
                self._site_index[episode.site_domain] = []
            if episode.episode_id not in self._site_index[episode.site_domain]:
                self._site_index[episode.site_domain].append(episode.episode_id)
        
        # LRU eviction if over capacity
        if len(self._episodes) > self.max_episodes:
            self._evict_episodes()
        
        logger.info(f"Stored episode {episode.episode_id} (task_type={episode.task_type})")
        return episode.episode_id

    async def delete_episode(self, episode_id: str) -> bool:
        """Drop one episode (corrupted heals, replaced discoveries). Returns
        whether anything was removed."""
        entry = self._episodes.pop(episode_id, None)
        if entry is None:
            return False
        domain = entry.episode.site_domain
        if domain and episode_id in self._site_index.get(domain, []):
            self._site_index[domain].remove(episode_id)
            if not self._site_index[domain]:
                del self._site_index[domain]
        return True
    
    async def access_episode(self, episode_id: str) -> Optional[Episode]:
        """Mark an episode as accessed (for relevance scoring)."""
        entry = self._episodes.get(episode_id)
        if entry is None:
            return None
        
        entry.access_count += 1
        
        # TTL is age-based (created_at), not idle-based.
        if time.time() - entry.episode.created_at > self.ttl_seconds:
            await self.delete_episode(episode_id)
            return None
        entry.last_accessed = time.time()
        
        # Boost relevance for recently accessed
        entry.relevance_score = min(1.0, entry.relevance_score + 0.1)
        
        return entry.episode
    
    # --- Retrieval ---
    
    async def find_replay_candidate(
        self,
        task_type: str,
        url: str,
        requested_fields: Optional[List[str]] = None,
        min_coverage: float = 0.5,
    ) -> Tuple[Optional[Episode], float]:
        """Which cached episode should replay for this URL - or None.

        Ordered by what the caller actually means:
          1. the same page we already mapped (exact recorded URL);
          2. a form on the same host whose field identity CONTAINS the fields we
             were asked to fill (a re-keyed URL, e.g. ?form=7, is still the same
             form), ranked by coverage then by structural cosine.

        Coverage rather than plain cosine, because a request names 3 fields and a
        cached form knows 40: cosine of those sets is small even when the cached
        form is exactly right. min_coverage rejects a partial match instead of
        silently filling the wrong form.
        """
        from urllib.parse import urlparse

        host = urlparse(url).netloc or url
        cutoff = time.time() - self.ttl_seconds
        query_words: set[str] = set()
        for name in requested_fields or []:
            query_words.update(_words(name))
        query_vec = embed_tokens(sorted(query_words), self.embedding_dim)

        scored: List[Tuple[Episode, float]] = []
        for entry in self._episodes.values():
            episode = entry.episode
            if episode.task_type != task_type:
                continue
            if episode.created_at < cutoff:
                continue
            if episode.site_domain != host:
                continue
            if episode.metadata.get("url") == url:
                # An exact-URL match still has to be about the fields the
                # caller asked for. Without this, the first episode cached for
                # a URL - whoever cached it, for whatever fields - is replayed
                # for any request to that URL, executing cached clicks the
                # caller's request never described.
                if query_words:
                    field_words = set(episode_field_tokens(episode.actions))
                    coverage = len(query_words & field_words) / len(query_words)
                    if coverage < min_coverage:
                        continue
                await self.access_episode(episode.episode_id)
                return episode, 1.0
            if not query_words:
                continue
            field_words = set(episode_field_tokens(episode.actions))
            coverage = len(query_words & field_words) / len(query_words)
            if coverage < min_coverage:
                continue
            ep_vec = [float(x) for x in (episode.embedding or [])]
            cosine = (sum(query_vec[i] * ep_vec[i] for i in range(len(query_vec)))
                      if len(ep_vec) == len(query_vec) else 0.0)
            scored.append((episode, coverage + 0.1 * cosine))

        if not scored:
            return None, 0.0
        scored.sort(key=lambda item: item[1], reverse=True)
        best, score = scored[0]
        await self.access_episode(best.episode_id)
        return best, score

    async def update_episode_actions(self, episode_id: str,
                                     actions: List[Dict[str, Any]]) -> bool:
        """Replace a healed episode's action list and recompute its structural
        vector, so the next replay uses the repaired selectors."""
        entry = self._episodes.get(episode_id)
        if entry is None:
            return False
        entry.episode.actions = actions
        entry.episode.embedding = embed_tokens(
            episode_field_tokens(actions), self.embedding_dim)
        return True
    
    # --- PII Filtering ---
    
    def _has_pii(self, actions: List[Dict[str, Any]]) -> bool:
        """Check if actions contain PII that should be filtered."""
        # Short tokens match on word boundaries only ("pin" must not fire on
        # "spinning"); multi-word phrases match as normalized substrings.
        short = re.compile(r"\b(ssn|cvv|pin)\b")
        phrases = (
            "credit card", "social security", "password", "bank account",
            "account number", "routing number",
        )
        text_content = " ".join(
            str(a.get("description", "")) + " " + str(a.get("value", ""))
            for a in actions
        ).lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", text_content)
        if short.search(normalized):
            return True
        return any(phrase in f" {normalized} " for phrase in phrases)
    
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
        """Structural vector for the episode: signed feature hashing over the
        field identity recorded at discovery (labels, placeholders, selector
        names). See embed_tokens()."""
        return embed_tokens(episode_field_tokens(episode.actions), self.embedding_dim)
    
    # --- Eviction ---
    
    def _evict_episodes(self) -> None:
        """Evict least relevant episodes (LRU + relevance scoring)."""
        # Sort key negates every field, so ascending order puts the stalest,
        # least relevant, least accessed entries LAST - evict from the tail.
        scored = []
        for eid, entry in self._episodes.items():
            score = (
                -entry.last_accessed,  # older = higher score (evict first)
                -entry.relevance_score,  # lower relevance = higher score
                -entry.access_count  # lower access count = higher score
            )
            scored.append((score, eid))
        
        scored.sort()
        
        # Evict bottom 10%. The sort is ascending and the score negates every
        # field, so the LARGEST scores (stalest, least relevant, least used)
        # sit at the TAIL - evict from there. (Evicting the head removed the
        # hottest episodes first.)
        evict_count = max(1, len(self._episodes) // 10)
        for _, eid in scored[-evict_count:]:
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