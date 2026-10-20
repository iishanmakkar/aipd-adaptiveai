"""The Discovery -> Cache -> Replay -> Heal pipeline, offline.

Two defects this round found by RUNNING the stack, locked here:

1. Episodic vectors were a hash of (task_type, field count, outcome, domain),
   self-described in code as "a hash-based mock embedding for demo purposes",
   and the only caller passed `query_embedding=[]` - which scored 0.0 against
   everything. So "replay a cached form" never matched a cached form, and two
   genuinely different 8-field forms on one host were vector-identical.
2. HEAL was unreachable: /api/form-fill called fill_form only, and
   _surgical_repair built an LLM prompt, never sent it, and returned
   "repaired" from `len(actions) >= 2` - an invented result.
"""
from urllib.parse import urlparse

from app.agents.form.form_agent import FormAgent
from app.agents.form.healing_agent import HealingAgent
from app.services.episodic_memory import EpisodicMemory, Episode, episode_field_tokens


def _episode(eid: str, url: str, labels: list) -> Episode:
    actions = [
        {"type": "focus_and_type", "field_id": f"f{i}", "label": label,
         "placeholder": "", "selector": f"input:nth-of-type({i + 1})"}
        for i, label in enumerate(labels)
    ]
    return Episode(episode_id=eid, task_type="form_fill", aria_snapshot_b64="",
                   actions=actions, outcome="success", pii_filtered=True,
                   site_domain=urlparse(url).netloc, metadata={"url": url})


async def test_vector_reflects_the_fields_not_their_count():
    """Same field count, different form -> different vector. The old mock hashed
    the count, so these two were identical."""
    mem = EpisodicMemory()
    await mem.store_episode(_episode("a", "https://x.test/f1", ["Full Name", "Email", "PNR"]))
    await mem.store_episode(_episode("b", "https://x.test/f2", ["Caste", "Income", "Account Number"]))
    va = mem._episodes["a"].episode.embedding
    vb = mem._episodes["b"].episode.embedding
    assert len(va) == len(vb) == mem.embedding_dim
    assert sum(x * y for x, y in zip(va, vb)) < 0.5

    # The same form again (new URL) -> the same vector: structural, deterministic.
    await mem.store_episode(_episode("c", "https://x.test/f3", ["PNR", "Email", "Full Name"]))
    assert mem._episodes["c"].episode.embedding == va


async def test_vector_carries_no_answer_values():
    episode = _episode("a", "https://x.test/f1", ["Email"])
    episode.actions[0]["value"] = "asha@example.com"
    tokens = episode_field_tokens(episode.actions)
    assert "asha" not in tokens and "example" not in tokens and "com" not in tokens


async def test_replay_resolves_the_cached_form_it_belongs_to():
    mem = EpisodicMemory()
    await mem.store_episode(_episode("known", "https://book.test/tickets",
                                     ["From", "To", "Date", "Passengers"]))

    exact, score = await mem.find_replay_candidate("form_fill", "https://book.test/tickets")
    assert exact.episode_id == "known" and score == 1.0

    # Re-keyed URL of the same form: matched by the fields asked for.
    moved, moved_score = await mem.find_replay_candidate(
        "form_fill", "https://book.test/tickets?ref=9", requested_fields=["From", "To"])
    assert moved.episode_id == "known" and moved_score > 0

    # Different host, and a request whose fields the cached form never had:
    # no match rather than filling the wrong form.
    other, _ = await mem.find_replay_candidate("form_fill", "https://other.test/tickets",
                                               requested_fields=["From"])
    assert other is None
    partial, _ = await mem.find_replay_candidate("form_fill", "https://book.test/grievance",
                                                 requested_fields=["Caste", "Income"])
    assert partial is None


class _FakePage:
    def __init__(self, live_selectors):
        self.live = set(live_selectors)

    async def query_selector(self, selector):
        return object() if selector in self.live else None


class _FakeBrowser:
    """Stand-in for BrowserTool: a page whose markup moved."""

    def __init__(self, tree, live_selectors):
        self._tree = tree
        self._page = _FakePage(live_selectors)
        self.opened = False

    async def start(self): self.opened = True
    async def navigate(self, url): pass
    async def wait_for_load(self): pass
    async def stop(self): self.opened = False
    async def get_accessibility_tree(self): return {"tree": self._tree}


async def test_heal_relocates_stale_selectors_onto_the_live_page():
    mem = EpisodicMemory()
    episode = _episode("a", "https://book.test/tickets", ["From", "To"])
    episode.actions.append({"type": "click", "field_id": "r1", "label": "Sleeper",
                            "placeholder": "", "selector": "div[3] > input[1]"})
    await mem.store_episode(episode)

    live = [
        {"role": "textbox", "label": "From", "placeholder": "", "selector": "#from"},
        {"role": "textbox", "label": "To", "placeholder": "", "selector": "#to"},
        {"role": "radio", "label": "Sleeper", "placeholder": "", "selector": "#sleeper"},
    ]
    # The site re-rendered: every cached positional path is gone, the fields are
    # still there under their labels with real ids.
    agent = HealingAgent(browser=_FakeBrowser(live, {"#from", "#to", "#sleeper"}), memory=mem)
    result = await agent.heal_replay("a", "https://book.test/tickets")

    assert result["status"] == "repaired"
    assert result["repaired_fields"] == 3 and result["stale_fields"] == 3
    healed = mem._episodes["a"].episode
    assert [a["selector"] for a in healed.actions] == ["#from", "#to", "#sleeper"]
    assert len({a["selector"] for a in healed.actions}) == 3


async def test_heal_does_not_confuse_a_control_class():
    """A stale 'click Sleeper' radio must not be relocated onto the textbox that
    carries the same label."""
    mem = EpisodicMemory()
    episode = _episode("a", "https://book.test/t", ["From"])
    episode.actions = [{"type": "click", "field_id": "r1", "label": "Sleeper",
                        "placeholder": "", "selector": "div[9] > input[9]"}]
    await mem.store_episode(episode)

    live = [{"role": "textbox", "label": "Sleeper", "placeholder": "", "selector": "#wrong"}]
    agent = HealingAgent(browser=_FakeBrowser(live, set()), memory=mem)
    assert agent._relocate(episode.actions[0], live, set()) is None


async def test_fill_form_actually_reaches_the_heal_stage(monkeypatch):
    """The stage that no route could reach: replay fails -> heal -> replay again
    succeeds, and discovery is never paid for."""
    mem = EpisodicMemory()
    await mem.store_episode(_episode("known", "https://book.test/tickets",
                                     ["From", "To", "Passengers"]))
    agent = FormAgent(browser=_FakeBrowser([], set()), memory=mem)

    calls = {"discover": 0, "replay": 0, "heal": 0}

    async def no_discovery(url):
        calls["discover"] += 1
        raise AssertionError("discovery must not run once a heal restores the replay")
    agent.discovery_agent.discover_form = no_discovery

    async def replay_fails_then_works(episode_id, url, values=None):
        calls["replay"] += 1
        if calls["replay"] == 1:
            return {"status": "failed", "failure_count": 3, "replay_results": []}
        return {"status": "success", "success_count": 3, "replay_results": []}
    agent.replay_agent.replay_form = replay_fails_then_works

    async def heal(episode_id, url):
        calls["heal"] += 1
        return {"status": "repaired", "episode_id": episode_id, "repaired_fields": 3}
    agent.healing_agent.heal_replay = heal

    result = await agent.fill_form("https://book.test/tickets", replay=True,
                                   user_values={"From": "New Delhi", "To": "Chandigarh"})

    assert calls == {"discover": 0, "replay": 2, "heal": 1}
    assert result["status"] == "success" and result["action"] == "form_filled_after_heal"
    assert result["healed"]["repaired_fields"] == 3
