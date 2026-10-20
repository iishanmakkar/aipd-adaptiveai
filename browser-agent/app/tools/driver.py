"""Real headless-Chromium driver (Playwright) shared by all browser-agent tools.

Every method below drives a live page. Nothing is canned: navigation returns
the real HTTP status, snapshots come from the live DOM, screenshots are real
pixels, fills write into real elements. Failures raise or return error dicts.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SNAPSHOT_JS = """() => {
  const out = [];
  const els = document.querySelectorAll(
    'input, textarea, select, button, [role=textbox], [role=button], ' +
    '[role=combobox], [role=listbox], [role=searchbox], a[href], h1, h2, h3'
  );
    els.forEach((el) => {
      const tag = (el.tagName || '').toLowerCase();
      let label = el.getAttribute('aria-label') || '';
      if (!label && el.id) {
        const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (lab) label = lab.innerText || '';
      }
      if (!label) label = el.getAttribute('placeholder') || el.getAttribute('alt') || '';
      // Radios/checkboxes wrapped in a <label> carry their text in the
      // wrapper, not in the input's own innerText (which is empty) - found
      // live when "AC 3-tier" resolved to a hidden field instead.
      if (!label) {
        const wrap = el.closest('label');
        if (wrap) label = wrap.innerText || '';
      }
      if (!label) label = ((el.innerText || '').trim().split('\\n')[0] || '').slice(0, 80);
    let selector = '';
    if (el.id) selector = '#' + CSS.escape(el.id);
    else {
      const parts = [];
      let node = el;
      while (node && node.nodeType === 1 && parts.length < 4) {
        const t = node.tagName.toLowerCase();
        const parent = node.parentElement;
        let idx = 1;
        if (parent) {
          let sib = node.previousElementSibling;
          while (sib) { if (sib.tagName === node.tagName) idx++; sib = sib.previousElementSibling; }
        }
        parts.unshift(`${t}:nth-of-type(${idx})`);
        node = parent;
      }
      selector = parts.join(' > ');
    }
    out.push({tag, label: (label || '').trim(), selector,
              type: (el.getAttribute('type') || '').toLowerCase()});
  });
  return {title: document.title, url: location.href, nodes: out};
}"""


MONITOR_JS = """() => {
  if (window.__a11yMutationCount === undefined) {
    window.__a11yMutationCount = 0;
    new MutationObserver((muts) => {
      window.__a11yMutationCount += muts.length;
    }).observe(document.documentElement,
               {subtree: true, childList: true, characterData: true, attributes: true});
  }
  return {mutations: window.__a11yMutationCount,
          text: document.body ? document.body.innerText : ''};
}"""


class Driver:
    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._page = None

    async def start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError("playwright not installed; no simulated browser exists.") from e
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            ctx = await self._browser.new_context(viewport={"width": 1366, "height": 900})
            self._page = await ctx.new_page()
            self._page.set_default_timeout(self.timeout_ms)
            await self._guard_requests()
        except Exception:
            # Partial start (launch/context/page blew up after playwright
            # started) must not leak the driver process per request.
            await self.stop()
            raise

    async def _guard_requests(self) -> None:
        """Re-validate EVERY request the page makes, not just the entry URL.

        validate_browse_url() on the submitted URL alone admits two bypasses:
        a public URL 302ing to http://169.254.169.254/ (or any internal host),
        and DNS answers that change between validation and fetch (rebinding).
        The interceptor aborts any http(s) request whose CURRENT target fails
        the guard; non-http(s) schemes (ws/data/about) pass through untouched.
        """
        from urllib.parse import urlparse
        from app.tools.url_guard import validate_browse_url

        page = self._require_page()
        route = getattr(page, "route", None)
        if route is None:
            return  # test doubles without interception support

        async def _check(route):
            url = route.request.url
            try:
                if urlparse(url).scheme in ("http", "https"):
                    validate_browse_url(url)
            except ValueError:
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", _check)

    async def stop(self) -> None:
        # Null first, then close: if browser.close() throws, the fields must
        # still read stopped for the next start(), and a failing
        # playwright.stop() must not mask the original close error.
        browser, playwright = self._browser, self._playwright
        self._browser = None
        self._page = None
        self._playwright = None
        try:
            if browser is not None:
                await browser.close()
        finally:
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    logger.warning("playwright stop failed during driver teardown")

    def current_url(self) -> str:
        """Best-effort current page URL (empty when no page is loaded)."""
        try:
            page = self._require_page()
        except RuntimeError:
            return ""
        try:
            return page.url or ""
        except Exception:
            return ""

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("Driver.start() was not called - refusing to fake a page.")
        return self._page

    async def navigate(self, url: str) -> Dict[str, Any]:
        # Defense in depth: endpoints 422 first, but no caller reaches the
        # network with a forbidden URL even if a code path forgets to check.
        from app.tools.url_guard import validate_browse_url
        validate_browse_url(url)
        page = self._require_page()
        resp = await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("load", timeout=self.timeout_ms)
        except Exception:
            logger.warning("full load timed out for %s; continuing with live DOM", url)
        # Post-redirect truth: callers (session.url, robots checks, status)
        # must see where the browser actually is, not the requested URL.
        return {"url": page.url or url, "http_status": resp.status if resp else None,
                "title": await page.title()}

    async def snapshot(self) -> Dict[str, Any]:
        return await self._require_page().evaluate(SNAPSHOT_JS)

    async def screenshot_b64(self) -> str:
        data = await self._require_page().screenshot(type="jpeg", quality=70)
        return base64.b64encode(data).decode()

    async def fill(self, selector: str, value: str) -> Dict[str, Any]:
        page = self._require_page()
        el = await page.query_selector(selector)
        if el is None:
            return {"status": "error", "detail": f"no element matches {selector!r}"}
        tag = await el.evaluate("(e) => e.tagName.toLowerCase()")
        if tag == "select":
            await el.select_option(value)
        else:
            await el.fill(value)
        readback = await el.evaluate("(e) => e.value !== undefined ? e.value : e.innerText")
        return {"status": "completed", "selector": selector, "readback": readback}

    async def select(self, selector: str, value: str) -> Dict[str, Any]:
        """Select a dropdown option; non-select elements are a caller bug."""
        page = self._require_page()
        el = await page.query_selector(selector)
        if el is None:
            return {"status": "error", "detail": f"no element matches {selector!r}"}
        tag = await el.evaluate("(e) => e.tagName.toLowerCase()")
        if tag != "select":
            raise ValueError(f"select needs a <select> element, got <{tag}> for {selector!r}")
        await el.select_option(value)
        readback = await el.evaluate("(e) => e.value !== undefined ? e.value : e.innerText")
        return {"status": "completed", "selector": selector, "readback": readback}

    async def click(self, selector: str) -> Dict[str, Any]:
        page = self._require_page()
        el = await page.query_selector(selector)
        if el is None:
            return {"status": "error", "detail": f"no element matches {selector!r}"}
        await el.click()
        return {"status": "completed", "selector": selector}

    async def extract_text(self, selector: Optional[str] = None) -> Dict[str, Any]:
        page = self._require_page()
        if selector:
            el = await page.query_selector(selector)
            if el is None:
                return {"status": "error", "detail": f"no element matches {selector!r}"}
            text = await el.inner_text()
        else:
            text = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 8000) : ''")
        return {"status": "completed", "text": text}

    async def monitor_signal(self) -> Dict[str, Any]:
        """One cheap page.evaluate: DOM-mutation count + visible text.

        The MutationObserver is installed on first call and survives for the
        life of the page; navigation resets the counter to 0 (new JS context).
        This is the Round 9 change-detection signal: a real DOM-mutation read,
        not pixel diffing, and it costs one evaluate per poll - no screenshot,
        no network, no model call.
        """
        return await self._require_page().evaluate(MONITOR_JS)
