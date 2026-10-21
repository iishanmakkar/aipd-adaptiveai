"""Accessibility snapshot tests for extension/src/ax.js, run in a REAL Chromium.

Why a browser and not jsdom: the behaviours being asserted are browser
behaviours. `el.labels`, `checkValidity()`, `getBoundingClientRect()`,
computed `display:none`, shadow-root ownership and `closest()` are exactly what a
DOM shim approximates badly. A green test against a stub that gets names wrong
would be the same class of fiction this repository just spent a pass removing.

Run:  python -m pytest extension/test -p no:warnings
"""
import json
import os

import pytest
from playwright.sync_api import sync_playwright

AX_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "src", "ax.js")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.add_init_script(path=AX_JS)
    # Init scripts run on navigation. The starting about:blank document never
    # navigated, so without this the module simply isn't there and every test
    # fails with "AdaptiveAIAX is not defined" - a harness bug wearing the
    # costume of 17 product bugs.
    pg.goto("about:blank")
    yield pg
    ctx.close()


def snapshot(page, html):
    """Load `html`, read the snapshot the real engine produced, JSON round-trip
    it so attribute access below is exactly what a content script would send."""
    page.set_content("<!doctype html><html><head><title>P</title></head><body>"
                     + html + "</body></html>")
    return json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))


def find(snap, label):
    for node in snap["nodes"]:
        if node.get("name") == label:
            return node
    raise AssertionError(f"no node named {label!r}; got "
                         f"{[n.get('name') for n in snap['nodes']]}")


def test_native_label_becomes_the_accessible_name(page):
    snap = snapshot(page, '<label for="pname">Passenger name</label><input id="pname">')
    node = find(snap, "Passenger name")
    assert node["nameSource"] == "native-label"
    assert node["role"] == "textbox"
    assert node["interactive"] is True
    assert node["kind"] == "text"


def test_aria_label_beats_the_native_label(page):
    """AccName precedence: ARIA overrides markup. Getting this backwards is how
    an assistant announces the wrong control's text."""
    snap = snapshot(page,
                    '<label for="a">Seat 12A</label>'
                    '<input id="a" aria-label="Choose seat 12A window">')
    node = find(snap, "Choose seat 12A window")
    assert node["nameSource"] == "aria-label"


def test_labelledby_beats_aria_label_and_resolves_ids(page):
    snap = snapshot(page,
                    '<p id="hdr">Departure city</p>'
                    '<input aria-label="ignored" aria-labelledby="hdr">')
    node = find(snap, "Departure city")
    assert node["nameSource"] == "labelledby"


def test_button_and_link_names(page):
    snap = snapshot(page,
                    '<button>Book tickets</button>'
                    '<a href="/help">Help with booking</a>')
    assert find(snap, "Book tickets")["role"] == "button"
    link = find(snap, "Help with booking")
    assert link["role"] == "link"


def test_placeholder_named_control_is_flagged_low_confidence(page):
    """A placeholder is not a label: it disappears once the user types, so a
    control whose only name is a placeholder is a real accessibility defect."""
    snap = snapshot(page, '<input placeholder="Enter email">')
    node = find(snap, "Enter email")
    assert node["nameSource"] == "placeholder"
    assert node["lowConfidenceName"] is True


def test_image_alt_states_are_distinguished(page):
    snap = snapshot(page,
                    '<img alt="A red circle" src="data:image/gif;base64,R0lGODlhAQABAAACAP///w==">'
                    '<img src="data:image/gif;base64,R0lGODlhAQABAAACAP///w==">'
                    '<img alt="" src="data:image/gif;base64,R0lGODlhAQABAAACAP///w==">')
    imgs = [n for n in snap["nodes"] if n["tag"] == "img"]
    assert len(imgs) == 3
    sources = sorted(n["nameSource"] for n in imgs)
    assert sources == ["alt", "alt-empty", "missing-alt"]
    # Only the one with NO alt attribute is a defect worth announcing: alt="" is
    # an author saying "decorative", and reporting it would be noise.
    assert snap["stats"]["missingAlt"] == 1


def test_hidden_content_is_excluded(page):
    snap = snapshot(page,
                    '<input id="v1" aria-label="Visible field">'
                    '<input style="display:none" aria-label="Display none field">'
                    '<input type="hidden" value="csrf">'
                    '<div aria-hidden="true"><button aria-label="Hidden button">x</button></div>')
    names = [n["name"] for n in snap["nodes"]]
    assert "Visible field" in names
    assert "Display none field" not in names
    assert "Hidden button" not in names
    assert "csrf" not in names
    assert snap["stats"]["hiddenSkipped"] >= 3


def test_presentation_role_is_honoured(page):
    snap = snapshot(page,
                    '<div role="presentation" aria-label="Box"><button aria-label="Real">x</button></div>')
    assert [n["name"] for n in snap["nodes"]] == ["Real"]


def test_checkbox_state_comes_from_the_real_element(page):
    snap = snapshot(page, '<label><input type="checkbox"> I accept terms</label>')
    node = find(snap, "I accept terms")
    assert node["role"] == "checkbox"
    assert node["states"]["checked"] is False

    page.locator('input[type=checkbox]').click()
    after = json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))
    assert find(after, "I accept terms")["states"]["checked"] is True


def test_required_empty_field_is_reported_invalid(page):
    """Constraint validation is the page's own 'this field is wrong' signal.
    Without it, an inline error a user cannot see stays invisible to the
    assistant, which is the exact gap await_change closes."""
    snap = snapshot(page, '<label for="r">Email address</label>'
                         '<input id="r" type="email" required>')
    node = find(snap, "Email address")
    assert node["states"]["invalid"] is True
    assert node["states"]["required"] is True


def test_select_roles_and_options(page):
    snap = snapshot(page,
                    '<label for="c">Travel class</label>'
                    '<select id="c"><option value="sleeper">Sleeper</option>'
                    '<option value="ac" selected>AC</option></select>'
                    '<label for="m">Seats wanted</label>'
                    '<select id="m" multiple><option value="1">1</option></select>')
    combo = find(snap, "Travel class")
    assert combo["role"] == "combobox"
    assert combo["kind"] == "select"
    assert [o["text"] for o in combo["options"]] == ["Sleeper", "AC"]
    assert [o["value"] for o in combo["options"] if o["selected"]] == ["ac"]
    assert find(snap, "Seats wanted")["role"] == "listbox"


def test_heading_level_and_live_regions(page):
    snap = snapshot(page,
                    '<h2>Choose your seats</h2>'
                    '<div role="status" aria-label="Booking status">Saved</div>'
                    '<div aria-live="assertive" aria-label="Alert zone">Error</div>')
    heading = find(snap, "Choose your seats")
    assert heading["role"] == "heading" and heading["level"] == 2
    assert find(snap, "Booking status")["live"] == "polite"
    assert find(snap, "Alert zone")["live"] == "assertive"


def test_password_value_is_never_read(page):
    """The credential must not exist in the snapshot at all: this object is what
    gets sent to the backend as page structure and what gets logged."""
    snap = snapshot(page, '<label for="pw">Password</label>'
                         '<input id="pw" type="password" value="hunter2!secret">')
    node = find(snap, "Password")
    assert node["kind"] == "password"
    assert node["sensitive"] is True
    assert "value" not in node or node["value"] is None
    assert node["hasValue"] is False
    assert "hunter2" not in json.dumps(snap)


def test_open_shadow_dom_control_is_found_and_marked(page):
    snap = snapshot(page,
                    '<w-card></w-card>'
                    '<script>customElements.define("w-card", class extends HTMLElement {'
                    'connectedCallback(){const r=this.attachShadow({mode:"open"});'
                    'r.innerHTML="<label>Qty on shadow<input></label>";}});</script>')
    node = find(snap, "Qty on shadow")
    assert node["inShadow"] is True, "shadow content must be visible to the assistant"


def test_identity_token_changes_when_the_slot_is_a_different_control(page):
    """Structural selectors are fragile by nature. The guard is that every node
    carries role|tag|name, so a reused position is detected instead of acted on."""
    snap = snapshot(page, '<label for="x">Passenger name</label><input id="x">')
    before = find(snap, "Passenger name")["identity"]
    page.evaluate("""() => {
        const el = document.getElementById('x');
        const btn = document.createElement('button');
        btn.id = 'x';
        btn.textContent = 'Book tickets';
        el.replaceWith(btn);
    }""")
    after_snap = json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))
    node = next(n for n in after_snap["nodes"] if n["selector"] == "#x")
    assert node["role"] == "button", node
    assert node["identity"] != before, "a reused slot must not look like the same control"


def test_names_match_chromes_own_accessibility_tree(page):
    """Differential test against the authority.

    Accessible names are a spec with many corners, and I am not a reliable judge
    of them from memory. Chrome's computed AX tree is the thing NVDA actually
    reads, so if my snapshot disagrees with it, mine is wrong. This test makes
    that check mechanical instead of a debate.
    """
    snap = snapshot(page, """
      <label for="a">Passenger name</label><input id="a">
      <input id="b" aria-label="Seat number">
      <label for="c">Travel class</label>
      <select id="c"><option value="s">Sleeper</option></select>
      <button>Book tickets</button>
      <a href="/help">Help with booking</a>
      <input type="checkbox" id="d"><label for="d">I accept terms</label>
      <label for="e">Enter email</label><input id="e" placeholder="you@example.com">
    """)
    mine = {n["name"] for n in snap["nodes"] if n["interactive"] and n["name"]}

    cdp = page.context.new_cdp_session(page)
    cdp.send("Accessibility.enable")
    tree = cdp.send("Accessibility.getFullAXTree")["nodes"]
    cdp.detach()
    chrome_names = {
        (n.get("name") or {}).get("value")
        for n in tree
        if not n.get("ignored") and (n.get("name") or {}).get("value")
    }
    missing = sorted(mine - chrome_names)
    assert not missing, f"names I invented that Chrome does not compute: {missing}"
    for expected in ("Passenger name", "Seat number", "Travel class",
                     "Book tickets", "Help with booking", "I accept terms", "Enter email"):
        assert expected in mine, f"{expected!r} not in my snapshot"



def test_document_order_and_bounds_are_reported(page):
    snap = snapshot(page,
                    '<label for="a">First field</label><input id="a"><br>'
                    '<label for="b">Second field</label><input id="b">')
    first = find(snap, "First field")
    second = find(snap, "Second field")
    assert first["bounds"]["y"] < second["bounds"]["y"], "vertical order is how it is announced"
    assert snap["nodes"].index(first) < snap["nodes"].index(second)


def test_stats_are_coherent(page):
    snap = snapshot(page,
                    '<input aria-label=""><button>No name needed</button>'
                    '<input placeholder="Ghost field">')
    assert snap["stats"]["total"] == len(snap["nodes"])
    assert snap["stats"]["interactive"] == sum(1 for n in snap["nodes"] if n["interactive"])
    assert snap["stats"]["unnamedControls"] == 1
    assert snap["title"] == "P"


def test_a_ref_still_names_the_same_element_after_the_page_inserts_nodes(page):
    """The regression that mattered most.

    Refs used to be positional, so one inserted node shifted every later ref onto a
    different control - and because the actor's identity check was computed from
    that same re-read node, nothing looked wrong. It surfaced in the task runner,
    where a click meant for "Pay ₹640" landed on an alert div and reported
    'pressed' while the payment button was never touched."""
    snap = snapshot(page, '<label for="a">Passenger Name</label><input id="a">'
                         '<button>Pay ₹640</button>')
    ref = find(snap, "Pay ₹640")["ref"]

    page.evaluate("""() => {
        const d = document.createElement('div');
        d.setAttribute('role', 'alert');
        d.textContent = 'Seat 12A held';
        document.body.prepend(d);
    }""")
    after = json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))
    matches = [n for n in after["nodes"] if n["ref"] == ref]
    assert len(matches) == 1, [n["ref"] for n in after["nodes"]]
    assert matches[0]["name"] == "Pay ₹640", matches[0]
