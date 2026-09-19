"""Real Playwright browser driver for the form-filler pipeline.

This is the concrete driver the Discovery/Cache/Healing/Replay agents drive:
a real headless Chromium (Playwright) that navigates real pages, reads the real
accessibility tree, takes real screenshots, and describes them through the real
NIM vision model. There is no simulated browser here: if Chromium cannot start
or the page cannot load, these methods raise instead of inventing data.

Interface (what the agents call):
  start() / stop() / navigate(url) / wait_for_load()
  get_accessibility_tree() -> {"tree": [{tag, role, label, innerText}]}
  get_vlm_description(prompt) -> {"status": "success", "description": ...}
  screenshot_b64() -> base64 jpeg
  _page -> the live Playwright Page (used by replay for selectors)
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BrowserTool:
    """Headless-Chromium driver (Playwright, async API). Lazily started."""

    def __init__(self, headless: bool = True, default_timeout_ms: int = 30000):
        self.headless = headless
        self.default_timeout_ms = default_timeout_ms
        self._playwright = None
        self._browser = None
        self._page = None

    # -- lifecycle --

    async def start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "playwright is not installed - install it (pip install playwright) "
                "and provision Chromium (playwright install chromium). No simulated "
                "browser fallback exists."
            ) from e
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        context = await self._browser.new_context(viewport={"width": 1366, "height": 900})
        self._page = await context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)

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
            raise RuntimeError("BrowserTool.start() was not called (or it failed) - refusing to fake a page.")
        return self._page

    # -- navigation --

    async def navigate(self, url: str) -> Dict[str, Any]:
        # Defense in depth: endpoints 422 first, but no caller reaches the
        # network with a forbidden URL even if a code path forgets to check.
        from app.api.url_guard import validate_browse_url
        validate_browse_url(url)
        page = self._require_page()
        response = await page.goto(url, wait_until="domcontentloaded")
        status = response.status if response else None
        return {"url": url, "http_status": status}

    async def wait_for_load(self, state: str = "load") -> None:
        page = self._require_page()
        try:
            await page.wait_for_load_state(state, timeout=self.default_timeout_ms)
        except Exception:
            # Pages with endless polling (analytics, live feeds) never reach full
            # "load"; the DOM we need is already there. Fall back honestly.
            logger.warning("wait_for_load_state(%s) timed out; continuing with current DOM", state)

    async def go_back(self) -> None:
        await self._require_page().go_back(wait_until="domcontentloaded")

    # -- perception --

    async def get_accessibility_tree(self) -> Dict[str, Any]:
        """Real interactive-element tree from the live DOM, flattened to the node
        shape the discovery agent parses ({tag, role, label, innerText}).

        Built with page.evaluate over the actual rendered document (labels,
        placeholders, aria attributes, required state) - the same ground truth
        an assistive technology consumes.
        """
        page = self._require_page()
        nodes = await page.evaluate("""() => {
          const out = [];
          const els = document.querySelectorAll(
            'input, textarea, select, button, [role=textbox], [role=button], ' +
            '[role=combobox], [role=listbox], [role=searchbox], a[href]'
          );
          els.forEach((el) => {
            const tag = (el.tagName || '').toLowerCase();
            const type = (el.getAttribute('type') || '').toLowerCase();
            let role = el.getAttribute('role') || '';
            if (!role) {
              if (tag === 'textarea') role = 'textarea';
              else if (tag === 'select') role = 'combobox';
              else if (tag === 'button') role = 'button';
              else if (tag === 'input' && ['submit','button','reset'].includes(type)) role = 'button';
              else if (tag === 'input' && type === 'radio') role = 'radio';
              else if (tag === 'input' && type === 'checkbox') role = 'checkbox';
              else if (tag === 'input' && type === 'search') role = 'search';
              else if (tag === 'input') role = 'textbox';
              else if (tag === 'a') role = 'link';
            }
            let label = el.getAttribute('aria-label') || '';
            if (!label && el.id) {
              const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              if (lab) label = lab.innerText || '';
            }
            // Implicit <label><input> wrapping (radios, checkboxes).
            if (!label && el.closest) {
              const wrap = el.closest('label');
              if (wrap) label = (wrap.innerText || '').trim();
            }
            if (!label) label = el.getAttribute('placeholder') || el.getAttribute('alt') || '';
            if (!label && (role === 'button' || tag === 'button' || tag === 'a'))
              label = (el.innerText || el.value || '').trim();
            const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
            let selector = '';
            if (el.id) selector = '#' + CSS.escape(el.id);
            else {
              const parts = [];
              let node = el;
              while (node && node.nodeType === 1 && parts.length < 4) {
                const tag = node.tagName.toLowerCase();
                const parent = node.parentElement;
                let idx = 1;
                if (parent) {
                  let sib = node.previousElementSibling;
                  while (sib) { if (sib.tagName === node.tagName) idx++; sib = sib.previousElementSibling; }
                }
                parts.unshift(`${tag}:nth-of-type(${idx})`);
                node = parent;
              }
              selector = parts.join(' > ');
            }
            out.push({
              tag, role: role.toLowerCase(), label: (label || '').trim(),
              innerText: ((el.innerText || '').trim() || (label || '').trim()),
              required: !!(el.required || el.getAttribute('aria-required') === 'true'),
              placeholder: el.getAttribute('placeholder') || '',
              selector, visible: !!(rect && rect.width > 0 && rect.height > 0),
            });
          });
          return out;
        }""")
        return {"tree": nodes or []}

    async def screenshot_b64(self) -> str:
        data = await self._require_page().screenshot(type="jpeg", quality=70)
        return base64.b64encode(data).decode()

    async def get_vlm_description(self, prompt: str) -> Dict[str, Any]:
        """Real vision description: screenshot -> NIM vision model. Raises on
        missing key or upstream failure (never a canned description)."""
        from app.config import settings

        if not settings.nim_api_key:
            raise RuntimeError("VLM not configured: NIM_API_KEY is missing.")
        import httpx

        image_b64 = await self.screenshot_b64()
        url = settings.nim_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": settings.nim_model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            "max_tokens": 500,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {settings.nim_api_key}"},
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
        return {"status": "success", "description": text}
