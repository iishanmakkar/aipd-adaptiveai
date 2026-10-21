"""BrowserAgent.execute_task used to consult a per-session `pattern_cache` before
running a tool: a repeated (session, tool, action) returned the PREVIOUS result,
flagged `cached`, and was counted in `steps_completed`. A second click therefore
reported "completed" having touched nothing.

Nothing may report a step it did not execute. These tests pin that.
"""
import pytest

from app.services.browser_agent import BrowserAgent


class CountingTool:
    """Records how many times it actually ran, and can be made to fail."""

    def __init__(self, status="completed"):
        self.calls = 0
        self.status = status

    async def execute(self, action, **args):
        self.calls += 1
        return {"status": self.status, "action": action, "ran": self.calls}


class FakeDriver:
    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


def agent_with(tool, steps=None):
    a = BrowserAgent(session_id="s1", driver=FakeDriver())
    a.tools = {"browser": tool}
    if steps is None:
        steps = [
            {"tool": "browser", "action": "click", "args": {}},
            {"tool": "browser", "action": "click", "args": {}},
        ]
    a._plan_task = lambda intent, ctx: steps
    return a


@pytest.mark.asyncio
async def test_repeated_step_executes_twice_not_replayed():
    tool = CountingTool()
    out = await agent_with(tool).execute_task("snapshot", {})
    assert tool.calls == 2, "second identical step was replayed from cache"
    assert out["steps_completed"] == 2


@pytest.mark.asyncio
async def test_no_cached_flag_can_appear_on_a_result():
    out = await agent_with(CountingTool()).execute_task("snapshot", {})
    assert not any("cached" in r for r in out["results"])


@pytest.mark.asyncio
async def test_error_steps_are_not_counted_as_completed():
    out = await agent_with(CountingTool(status="error")).execute_task("snapshot", {})
    assert out["steps_completed"] == 0
    assert out["steps_failed"] == 2


@pytest.mark.asyncio
async def test_driver_always_stops_even_when_a_tool_raises():
    class ExplodingTool:
        async def execute(self, action, **args):
            raise RuntimeError("page vanished")

    driver = FakeDriver()
    a = BrowserAgent(session_id="s3", driver=driver)
    a.tools = {"browser": ExplodingTool()}
    a._plan_task = lambda intent, ctx: [{"tool": "browser", "action": "click", "args": {}}]
    out = await a.execute_task("snapshot", {})
    assert driver.stopped is True, "chromium leaked after a tool exception"
    assert out["steps_failed"] == 1


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_not_silently_skipped():
    out = await agent_with(CountingTool(), steps=[{"tool": "nope", "action": "x"}]
                            ).execute_task("snapshot", {})
    assert out["steps_failed"] == 1
    assert "Unknown tool" in out["results"][0]["detail"]


@pytest.mark.asyncio
async def test_natural_language_intent_is_declared_exploratory_not_planned():
    """_plan_task matched only literal verb keys (navigate_to_url, fill_field...)
    and ran one fixed three-step page sniff for everything else, narrating it as
    though it had planned the request. A goal like "book me two seats" is not a
    key, so it must be declared as a look-around, not as a completed booking."""
    driver = FakeDriver()
    a = BrowserAgent(session_id="s4", driver=driver)
    a.tools = {"accessibility_tree": CountingTool(), "browser": CountingTool()}
    out = await a.execute_task("book me two seats to Chandigarh", {})

    assert out["unsupported_intent"] is True
    assert out["status"] == "exploratory"
    assert "not a booking" in out["narration"]
    assert driver.stopped is True


@pytest.mark.asyncio
async def test_recognised_verb_is_not_marked_exploratory():
    driver = FakeDriver()
    a = BrowserAgent(session_id="s5", driver=driver)
    a.tools = {"browser": CountingTool()}
    out = await a.execute_task("navigate_to_url", {"url": "http://example.com"})
    assert out["status"] == "planned"
    assert out["unsupported_intent"] is False
    assert out["steps_completed"] == 1


@pytest.mark.asyncio
async def test_exploratory_path_does_not_call_the_vision_tool():
    """The sniff used to include vlm_analysis, which hard-fails without an API
    key and turned a clean "I only looked" into a 502-shaped step."""
    a = BrowserAgent(session_id="s6", driver=FakeDriver())
    vlm = CountingTool(status="error")
    a.tools = {"accessibility_tree": CountingTool(), "browser": CountingTool(),
               "vlm_analysis": vlm}
    await a.execute_task("tell me about this page", {})
    assert vlm.calls == 0
