"""Live-site proof for the extension's perception layer.

Everything else in extension/test runs against fixtures I wrote, which means they
can only prove the module agrees with my own idea of a page. This runs the loaded
extension against real production markup and asks the questions that matter:

  can it see the page at all, how long does it take, how many controls have no
  accessible name, how many images have no alt text, and - read-only - which
  controls WOULD the spending gate stop?

It never logs in, never fills a field, never clicks. The output is a redacted
snapshot: page structure, no values, because a proof artifact that quotes
someone's session state is a leak with a nice filename.

Exit code is non-zero when the page could not be read, when the snapshot agrees
with nothing Chrome itself computes, or when the extension never loaded - a run
that "completed" while seeing nothing is the failure mode this repo already
needed a whole pass to remove.

Usage:
    python scripts/extension_live_site_proof.py [site ...]
    python scripts/extension_live_site_proof.py            # default list
"""
import json
import os
import re
import sys
import time
from datetime import date

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_DIR = os.path.join(REPO, "extension")
OUT_ROOT = os.path.join(REPO, "docs", "proofs")


def safe_dir_name(name: str) -> str:
    """Output directories are named after site labels; keep them to plain
    identifier characters so a label can never place a write outside
    docs/proofs, wherever the label came from."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")
    return cleaned or "site"

DEFAULT_SITES = [
    # The three the design promises to reach. Expect these to be inconclusive from
    # an automated browser: they run anti-bot, and evading it is refused in the
    # spec, so a block here is the harness being honest, not the product failing.
    ("bookmyshow", "https://in.bookmyshow.com/"),
    ("irctc", "https://www.irctc.co.in/nget/train-search"),
    ("swiggy", "https://www.swiggy.com/"),
    # Complex, real, unblocked markup - what proves the perception layer itself.
    ("mdn", "https://developer.mozilla.org/en-US/"),
    ("mdn-aria", "https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA"),
    ("hackernews", "https://news.ycombinator.com/"),
    ("wikipedia", "https://en.wikipedia.org/wiki/Web_Accessibility"),
    ("railyatri", "https://www.railyatri.in/"),
]


FAILURES = []
BLOCKED = []

# A block interstitial is a full page with buttons and correct accessible names, so
# a naive probe "succeeds" on it. The first run of this script did exactly that on
# BookMyShow and reported all checks passed against a 47-element Cloudflare wall.
# Being blocked is also not a product failure: this is an automated browser with a
# fresh profile, and not evading anti-bot is a decision, not a defect. So it is
# reported as inconclusive - exit 3 - never as a pass.
BLOCK_MARKERS = (
    "attention required", "cloudflare", "verify you are human", "just a moment",
    "access denied", "are you a robot", "request blocked", "pardon our interruption",
    "unusual traffic", "captcha", "wikimedia error", "rate limit",
)

MIN_REAL_DOM_ELEMENTS = 200
SKIPPED = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
        return True
    print(f"  FAIL: {msg}", file=sys.stderr)
    FAILURES.append(msg)
    return False


def looks_blocked(title, url, dom_elements):
    hay = f"{title} {url}".lower()
    if any(m in hay for m in BLOCK_MARKERS):
        return "challenge/block marker in title or url"
    if dom_elements < MIN_REAL_DOM_ELEMENTS:
        return f"only {dom_elements} DOM elements (a content site is far larger)"
    return None


def chrome_ax_names(page):
    """Names as Chrome's own accessibility engine computes them, for differential
    comparison. This is the same trick the fixture tests use; on a real page it
    stops being a self-consistency check."""
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Accessibility.enable")
        tree = cdp.send("Accessibility.getFullAXTree")["nodes"]
    finally:
        cdp.detach()
    out = set()
    for n in tree:
        if n.get("ignored"):
            continue
        value = (n.get("name") or {}).get("value")
        if value:
            out.add(value.strip())
    return out


SW_AUDIT = """async (siteUrl) => {
    // page.evaluate() runs in the page's MAIN world; content scripts live in an
    // isolated one, so the probe has to ask the extension the way its own service
    // worker does rather than reaching for a global that is not there.
    for (const tab of await chrome.tabs.query({})) {
        let a;
        try { a = await chrome.tabs.sendMessage(tab.id, { type: 'adaptiveai:audit' }); }
        catch (e) { continue; }
        if (a && a.url && a.url.startsWith(siteUrl)) return a;
    }
    return { error: 'no matching tab answered' };
}"""


def probe(context, name, url):
    print(f"\n=== {name}: {url}")
    page = context.new_page()
    started = time.time()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Real sites render after first paint; a snapshot taken too early measures
        # a skeleton and reports it as a page.
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)[:120]}"
        print(f"  SKIP: could not load ({reason})")
        SKIPPED.append((name, reason))
        page.close()
        return None

    loaded = True
    try:
        page.wait_for_function(
            "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
            timeout=20000)
    except Exception:
        loaded = False

    took_ms = int((time.time() - started) * 1000)
    final_url = page.url
    result = {
        "site": name, "url": url, "loaded_extension": loaded,
        "ms_to_first_snapshot": took_ms, "final_url": final_url,
    }

    if not check(loaded, f"{name}: content script ran (extension loaded)"):
        page.close()
        return result

    sw = None
    deadline = time.time() + 20
    while time.time() < deadline:
        for candidate in context.service_workers:
            if candidate.url.startswith("chrome-extension://"):
                sw = candidate
                break
        if sw:
            break
        time.sleep(0.4)
    if sw is None:
        check(False, f"{name}: no service worker to ask for an audit")
        page.close()
        return result

    audit = sw.evaluate(SW_AUDIT, final_url)
    if "error" in audit:
        check(False, f"{name}: audit failed - {audit['error']}")
        page.close()
        return result

    result["snapshot_ms"] = audit["snapshotMs"]
    result["dom_elements"] = audit["domElements"]
    result["stats"] = audit["stats"]
    result["title"] = audit["title"]
    result["nodes_total"] = len(audit["redacted"] or [])
    result["gate_would_stop"] = audit["gated"]
    nodes = audit["redacted"] or []

    blocked = looks_blocked(audit.get("title") or "", final_url, audit["domElements"])
    result["blocked"] = blocked
    if blocked:
        print(f"  INCONCLUSIVE: {name} - {blocked}")
        BLOCKED.append(name)
        day = date.today().isoformat()
        out_dir = os.path.join(OUT_ROOT, f"{day}-{safe_dir_name(name)}")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "snapshot-redacted.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        page.close()
        return result

    check(audit["snapshotMs"] < 4000,
          f"{name}: snapshot in {audit['snapshotMs']}ms on {audit['domElements']} elements")
    check(result["nodes_total"] > 5,
          f"{name}: found {result['nodes_total']} described elements")
    unnamed = audit["stats"]["unnamedControls"]
    interactive = max(1, audit["stats"]["interactive"])
    print(f"  info: {interactive} interactive, {unnamed} unnamed "
          f"({100 * unnamed // interactive}% of controls), "
          f"{audit['stats']['missingAlt']} images without alt, "
          f"{len(audit['gated'])} gated")
    check(unnamed / interactive < 0.6,
          f"{name}: under 60% of controls unnamed (got {100 * unnamed // interactive}%)")

    # Differential against Chrome's own engine. Not every name can be compared -
    # Chrome's tree includes container nodes this snapshot deliberately drops - so
    # the assertion is on the overlap being large, not perfect.
    try:
        ax = chrome_ax_names(page)
        mine = {n.get("name") for n in nodes if n.get("name")}
        overlap = len(mine & ax)
        rate = overlap / max(1, len(mine))
        print(f"  info: {overlap}/{len(mine)} names ({rate * 100:.0f}%) "
              f"also computed by Chrome's AX tree")
        check(rate > 0.5, f"{name}: majority of names agree with Chrome's own tree")
    except Exception as e:
        print(f"  info: AX comparison unavailable ({type(e).__name__})")

    day = date.today().isoformat()
    out_dir = os.path.join(OUT_ROOT, f"{day}-{safe_dir_name(name)}")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "snapshot-redacted.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    screenshot = os.path.join(out_dir, "page.png")
    try:
        page.screenshot(path=screenshot, full_page=False)
    except Exception:
        pass  # some sites veto screenshots; not a perception failure
    page.close()
    return result


def main():
    sites = sys.argv[1:]
    pairs = [s for s in DEFAULT_SITES if not sites or s[0] in sites]
    if sites and not pairs:
        print(__doc__)
        raise SystemExit(2)

    results = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            "", headless=True, channel="chromium",
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}"])
        for name, url in pairs:
            try:
                r = probe(ctx, name, url)
                if r:
                    results.append(r)
            except Exception as e:
                print(f"  FAIL: {name} probe raised {type(e).__name__}: {str(e)[:160]}",
                      file=sys.stderr)
                FAILURES.append(f"{name} raised")
        ctx.close()

    verified = [r for r in results if not r.get("blocked") and r.get("loaded_extension")]
    print(f"\n{len(pairs)} sites attempted: {len(verified)} read as real pages, "
          f"{len(BLOCKED)} blocked or error pages, {len(SKIPPED)} never loaded")
    for n, why in SKIPPED:
        print(f"  never loaded: {n} - {why}")
    for n in BLOCKED:
        print(f"  blocked/error page: {n}")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        raise SystemExit(1)
    if not verified:
        print("NOTHING WAS PROVEN: no site served a real page to an automated "
              "browser. This is inconclusive, not a pass.")
        raise SystemExit(3)
    print(f"perception verified on {len(verified)} real page(s): "
          + ", ".join(r["site"] for r in verified))
    if BLOCKED or SKIPPED:
        print("Being blocked is expected for an automated browser with a fresh "
              "profile, and evading it is refused by design (spec section 3). The "
              "vendor sites therefore still require the extension running in the "
              "user's own logged-in browser, which is not reproducible here.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
