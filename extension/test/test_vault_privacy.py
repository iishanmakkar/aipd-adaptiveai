"""Vault and redaction tests.

The vault runs in the service worker, where chrome.storage.local exists. Tests
inject an in-memory store with the same shape rather than stubbing the chrome
namespace, so what is exercised is the real code path against a real storage
contract.

The most important test here has a positive control: it proves the leak check
WOULD have caught a leak, because a redaction test that passes only because it
looks for nothing is worthless.

Run:  python -m pytest extension/test/test_vault_privacy.py -p no:warnings
"""
import json
import os

import pytest
from playwright.sync_api import sync_playwright

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

MEMORY_STORE = """
window.__memStore = (() => {
  const data = {};
  return {
    get(keys, cb) {
      const out = {};
      (Array.isArray(keys) ? keys : [keys]).forEach(k => {
        if (Object.prototype.hasOwnProperty.call(data, k)) out[k] = data[k];
      });
      cb(out);
    },
    set(obj, cb) { Object.assign(data, obj); cb && cb(); },
    remove(keys, cb) {
      (Array.isArray(keys) ? keys : [keys]).forEach(k => delete data[k]);
      cb && cb();
    },
  };
})();
"""


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
    pg.add_init_script(path=os.path.join(SRC, "ax.js"))
    pg.add_init_script(path=os.path.join(SRC, "vault.js"))
    pg.add_init_script(path=os.path.join(SRC, "privacy.js"))
    pg.add_init_script(MEMORY_STORE)
    pg.goto("about:blank")
    pg.evaluate("() => AdaptiveAIVault.useStore(window.__memStore)")
    yield pg
    ctx.close()


def canonical(page, label):
    return page.evaluate("(l) => AdaptiveAIVault.canonical(l)", label)


def test_page_vocabulary_resolves_to_one_profile_field(page):
    assert canonical(page, "Email address") == "email"
    assert canonical(page, "E-mail") in ("email", "e mail")
    assert canonical(page, "Mobile number") == "phone"
    assert canonical(page, "Passenger Name (required)") == "full name"
    assert canonical(page, "Citizen full name") == "full name"
    assert canonical(page, "Date of Birth") == "date of birth"
    assert canonical(page, "Permanent Account Number") == "pan number"
    assert canonical(page, "PIN code") == "pin code"


def test_substring_collisions_do_not_misfile_a_field(page):
    """'capacity' contains 'city' and 'username' contains 'name'. A field filed
    under the wrong label is worse than one the assistant admits it lacks."""
    assert canonical(page, "Capacity") != "city"
    assert canonical(page, "Username") != "full name"
    assert canonical(page, "Civility note") != "city"


def test_set_and_resolve_round_trip(page):
    out = json.loads(json.dumps(page.evaluate(
        """async () => {
            await AdaptiveAIVault.set('Email address', 'asha@example.com');
            return { stored: await AdaptiveAIVault.resolve('email'),
                     byPageLabel: await AdaptiveAIVault.resolve('Email address') };
        }""")))
    assert out["stored"] == "asha@example.com"
    assert out["byPageLabel"] == "asha@example.com"


def test_credentials_are_never_stored_or_resolved(page):
    out = json.loads(json.dumps(page.evaluate(
        """async () => {
            const attempt = await AdaptiveAIVault.set('Password', 'hunter2');
            const otp = await AdaptiveAIVault.set('Enter OTP', '648213');
            return { attempt, otp,
                     password: await AdaptiveAIVault.resolve('Password'),
                     labels: await AdaptiveAIVault.availableLabels() };
        }""")))
    assert out["attempt"]["ok"] is False
    assert out["otp"]["ok"] is False
    assert out["password"] is None
    assert not any("password" in l or l == "otp" for l in out["labels"])


def test_only_labels_may_ever_leave_the_device(page):
    out = json.loads(json.dumps(page.evaluate(
        """async () => {
            await AdaptiveAIVault.set('Passenger name', 'Asha Sharma');
            await AdaptiveAIVault.set('Aadhaar number', '123456789012');
            return { labels: await AdaptiveAIVault.availableLabels(),
                     blob: JSON.stringify(await AdaptiveAIVault.availableLabels()) };
        }""")))
    assert "full name" in out["labels"]
    assert "aadhaar number" in out["labels"]
    assert "Asha Sharma" not in out["blob"]
    assert "123456789012" not in out["blob"]


def test_wipe_removes_everything(page):
    out = json.loads(json.dumps(page.evaluate(
        """async () => {
            await AdaptiveAIVault.set('City', 'Chandigarh');
            await AdaptiveAIVault.wipe();
            return { labels: await AdaptiveAIVault.availableLabels(),
                     city: await AdaptiveAIVault.resolve('city') };
        }""")))
    assert out["labels"] == []
    assert out["city"] is None


FILLED_PAGE = """
<label for="n">Passenger Name</label><input id="n" value="Asha Sharma">
<label for="a">Aadhaar Number</label><input id="a" value="123456789012">
<label for="p">Password</label><input id="p" type="password" value="hunter2">
<label for="c">Travel class</label>
<select id="c"><option value="INTERNAL-CODE-9">AC 3-tier</option></select>
"""


def build_snapshots(page):
    page.set_content("<!doctype html><html><body>" + FILLED_PAGE + "</body></html>")
    return json.loads(json.dumps(page.evaluate(
        """() => {
            const snap = AdaptiveAIAX.computeSnapshot(document);
            return { raw: snap, redacted: AdaptiveAIPrivacy.redactSnapshot(snap) };
        }""")))


def test_redacted_snapshot_keeps_shape_and_drops_content(page):
    both = build_snapshots(page)
    raw_nodes, red_nodes = both["raw"]["nodes"], both["redacted"]["nodes"]
    assert len(red_nodes) == len(raw_nodes)
    for r in red_nodes:
        assert "value" not in r
        assert "selector" not in r
        assert "identity" not in r
        assert "bounds" not in r
        assert "name" in r and "role" in r and "kind" in r
    named = {n["name"]: n for n in red_nodes if n.get("name")}
    assert named["Passenger Name"]["hasValue"] is True
    assert named["Password"]["sensitive"] is True


def test_internal_option_codes_are_not_sent(page):
    both = build_snapshots(page)
    sel = next(n for n in both["redacted"]["nodes"] if n["role"] == "combobox")
    assert [o["text"] for o in sel["options"]] == ["AC 3-tier"]
    assert "value" not in sel["options"][0]
    assert "INTERNAL-CODE-9" not in json.dumps(both["redacted"])


def test_no_vault_value_appears_in_an_outgoing_request(page):
    """The guarantee, checked against a page that currently holds real values."""
    page.evaluate("""async () => {
        await AdaptiveAIVault.set('Passenger name', 'Asha Sharma');
        await AdaptiveAIVault.set('Aadhaar number', '123456789012');
    }""")
    both = build_snapshots(page)
    values = ["Asha Sharma", "123456789012", "hunter2"]
    leaked = page.evaluate(
        """([body, vals]) => AdaptiveAIPrivacy.findLeaks(body, vals)""",
        [both["redacted"], values])
    assert leaked == [], f"vault values reached the request body: {leaked}"


def test_the_leak_check_would_have_caught_it(page):
    """Positive control. Without this, the previous test could be passing because
    it detects nothing."""
    both = build_snapshots(page)
    leaked = page.evaluate(
        """([body, vals]) => AdaptiveAIPrivacy.findLeaks(body, vals)""",
        [both["raw"], ["Asha Sharma", "123456789012"]])
    assert sorted(leaked) == ["123456789012", "Asha Sharma"], leaked
