"""A choice click that leaves the box unchecked must not report success.

`_execute_replay_action` read `is_checked()`, and when the element was NOT
checked executed `pass  # report success w/ state` and returned
`status: "success"`. A blind user cannot look at the screen to catch that, and
every downstream count (fields filled, booking "confirmed") inherited the lie.

Method is `_execute_replay_action(action, values)`; the action dict's verb key
is `type`, and the page arrives via `self.browser._require_page()`.
"""
import pytest

from app.agents.form.replay_agent import ReplayAgent

ACTION = {"field_id": "f1", "label": "I agree", "type": "click",
          "is_action_button": False, "selector": "#f1"}
VALUES = {"I agree": "yes"}


class FakeField:
    def __init__(self, checked_from=None):
        self.clicks = 0
        # checked_from: click count at which the box reports checked
        self._checked_from = checked_from

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self, timeout=None):
        self.clicks += 1

    async def is_checked(self):
        if self._checked_from is None:
            return False
        return self.clicks >= self._checked_from


class FakePage:
    def __init__(self, field):
        self._field = field

    async def query_selector(self, selector):
        return self._field

    async def wait_for_load_state(self, state, timeout=None):
        return None


class FakeBrowser:
    def __init__(self, page):
        self._page = page

    def _require_page(self):
        return self._page


def replay_for(field):
    return ReplayAgent(browser=FakeBrowser(FakePage(field)))


@pytest.mark.asyncio
async def test_click_leaving_box_unchecked_is_not_success():
    field = FakeField(checked_from=None)
    out = await replay_for(field)._execute_replay_action(ACTION, VALUES)
    assert out["status"] != "success", "unchecked box reported success"
    assert out["status"] == "failed"
    assert "not checked" in out["reason"]


@pytest.mark.asyncio
async def test_retry_pass_is_acked_when_it_lands():
    """Some radios/checkboxes only flip on a second pass (label wiring); the
    retry is what lets that case be honest instead of a false success."""
    field = FakeField(checked_from=2)
    out = await replay_for(field)._execute_replay_action(ACTION, VALUES)
    assert out["status"] == "success"
    assert field.clicks == 2, "second click pass never ran"


@pytest.mark.asyncio
async def test_is_checked_raising_is_not_treated_as_verified():
    class ThrowingField(FakeField):
        async def is_checked(self):
            raise RuntimeError("detached")

    field = ThrowingField()
    out = await replay_for(field)._execute_replay_action(ACTION, VALUES)
    assert out["status"] == "failed"
