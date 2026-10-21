"""The first tests in this repository that launch a REAL Chromium.

Every other browser-agent test injects FakeDriver, which proves routing and
gating but proves nothing about perception: a fake driver cannot reveal that the
snapshot selector list missed a control, or that a fill did not stick. Those are
the failures that matter to a user who cannot see the page, and until now
"real Playwright" was a statement about the code rather than a checked fact.

Pages are `data:` URLs - self-contained, no network, and explicitly allowed by
app/tools/url_guard.py (which refuses loopback and private http without
ADAPTIVEAI_ALLOW_LOCAL_TARGETS). AUTOMATION_SAFETY.md is honoured: a
Playwright-launched browser, input only through page objects, never OS-level.
"""
import base64

import pytest

from app.tools.driver import Driver

BOOKING_PAGE = """<!doctype html><html><head><title>Fixture booking</title></head>
<body>
<form>
  <label for="pname">Passenger name</label><input id="pname" name="pname">
  <label for="seats">Seats</label><input id="seats" name="seats">
  <label for="cls">Travel class</label>
  <select id="cls"><option value="sleeper">Sleeper</option><option value="ac">AC</option></select>
  <label><input type="checkbox" id="ins"> I accept insurance</label>
  <button type="submit">Book tickets</button>
</form>
<img src="data:image/gif;base64,R0lGODlhAQABAAACAP///w==" alt="A red circle">
<img src="data:image/gif;base64,R0lGODlhAQABAAACAP///w==">
</body></html>"""


def data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


@pytest.fixture
async def live_driver():
    d = Driver()
    await d.start()
    try:
        yield d
    finally:
        await d.stop()


@pytest.mark.browser
@pytest.mark.asyncio
async def test_chromium_actually_starts_and_navigates(live_driver):
    nav = await live_driver.navigate(data_url(BOOKING_PAGE))
    assert nav["title"] == "Fixture booking", f"real title missing: {nav}"
    assert nav["url"].startswith("data:text/html")


@pytest.mark.browser
@pytest.mark.asyncio
async def test_snapshot_reads_real_labels_not_hashes(live_driver):
    """Perception contract: the page's own <label> text must reach the caller,
    because that text is what a screen reader would have said."""
    await live_driver.navigate(data_url(BOOKING_PAGE))
    snap = await live_driver.snapshot()
    labels = {n.get("label") for n in snap["nodes"]}
    for expected in ("Passenger name", "Seats", "Travel class", "Book tickets"):
        assert expected in labels, f"{expected!r} never surfaced; got {sorted(labels)}"


@pytest.mark.browser
@pytest.mark.asyncio
async def test_fill_is_read_back_from_the_real_dom(live_driver):
    await live_driver.navigate(data_url(BOOKING_PAGE))
    out = await live_driver.fill("#pname", "Asha Sharma")
    assert out["status"] == "completed"
    assert out["readback"] == "Asha Sharma", "fill reported done without sticking"


@pytest.mark.browser
@pytest.mark.asyncio
async def test_select_lands_on_the_chosen_option(live_driver):
    await live_driver.navigate(data_url(BOOKING_PAGE))
    out = await live_driver.select("#cls", "ac")
    assert out["readback"] == "ac"


@pytest.mark.browser
@pytest.mark.asyncio
async def test_click_changes_real_page_state(live_driver):
    """Driver.click has no outcome verification of its own - this pins what it
    does achieve today, and is the seam await_change closes in the extension
    plan (design spec 5.3)."""
    await live_driver.navigate(data_url(BOOKING_PAGE))
    before = await live_driver.snapshot()
    checkbox = next(n for n in before["nodes"] if n["tag"] == "input" and n["selector"] == "#ins")
    await live_driver.click(checkbox["selector"])
    page = live_driver._require_page()
    assert await page.evaluate("() => document.getElementById('ins').checked") is True


@pytest.mark.browser
@pytest.mark.asyncio
async def test_screenshot_is_real_rendered_bytes(live_driver):
    await live_driver.navigate(data_url(BOOKING_PAGE))
    b64 = await live_driver.screenshot_b64()
    assert len(b64) > 2000, f"suspiciously small screenshot: {len(b64)} chars"


@pytest.mark.browser
@pytest.mark.asyncio
async def test_unlabelled_image_is_visible_as_unlabelled(live_driver):
    """The page carries one alt'd image and one without. Perception must tell
    them apart - that is the trigger for the vision description, not a guess."""
    await live_driver.navigate(data_url(BOOKING_PAGE))
    snap = await live_driver.snapshot()
    imgs = [n for n in snap["nodes"] if n["tag"] == "img"]
    assert len(imgs) == 2, f"both images must appear, got {imgs}"
    labelled = [n for n in imgs if n.get("label")]
    assert len(labelled) == 1, "exactly one image has alt text"
    assert labelled[0]["label"] == "A red circle"
