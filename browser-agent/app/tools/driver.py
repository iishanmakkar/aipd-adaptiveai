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
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        ctx = await self._browser.new_context(viewport={"width": 1366, "height": 900})
        self._page = await ctx.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    async def stop(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            self._browser = None
            self._page = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("Driver.start() was not called - refusing to fake a page.")
        return self._page

    async def navigate(self, url: str) -> Dict[str, Any]:
        page = self._require_page()
        resp = await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("load", timeout=self.timeout_ms)
        except Exception:
            logger.warning("full load timed out for %s; continuing with live DOM", url)
        return {"url": url, "http_status": resp.status if resp else None,
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
