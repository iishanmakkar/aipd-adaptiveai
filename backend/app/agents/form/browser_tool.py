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

# One flat DOM pass over the LIVE page, flattened to the node shape the
# discovery agent parses. Reads the same ground truth an assistive technology
# consumes: labels (aria-label / aria-labelledby / label[for] / wrapping
# label / fieldset legend / name / placeholder), roles, state, visibility and
# a STABLE selector (id > name > data-testid > aria-label).
#
# Kept as a module constant: this Playwright build's Page.evaluate() takes
# (expression, arg) only — a timeout kwarg raises TypeError, which broke every
# discovery live ("discovery failed: RuntimeError", form-fill on any site).
TREE_JS = r"""() => {
          const out = [];
          const els = document.querySelectorAll(
            'input, textarea, select, button, [role=textbox], [role=button], ' +
            '[role=combobox], [role=listbox], [role=searchbox], [role=checkbox], ' +
            '[role=radio], [role=switch], [role=slider], [role=link], [role=search], ' +
            'a[href], a[onclick], [contenteditable="true"]'
          );
          els.forEach((el) => {
            const tag = (el.tagName || '').toLowerCase();
            const type = (el.getAttribute('type') || '').toLowerCase();
            // Hidden state/CSRF inputs are not fillable controls: caching
            // them as textboxes made every normal form report
            // "partial_success" over a field the user cannot see.
            if (tag === 'input' && type === 'hidden') return;
            let role = el.getAttribute('role') || '';
            if (!role) {
              if (tag === 'textarea') role = 'textarea';
              else if (tag === 'select') role = 'combobox';
              else if (tag === 'button') role = 'button';
              else if (tag === 'input' && ['submit','button','reset'].includes(type)) role = 'button';
              else if (tag === 'input' && type === 'radio') role = 'radio';
              else if (tag === 'input' && type === 'checkbox') role = 'checkbox';
              else if (tag === 'input' && type === 'search') role = 'search';
              else if (tag === 'input' && ['file','date','number','email','tel','url','password'].includes(type)) role = 'textbox';
              else if (tag === 'input') role = 'textbox';
              else if (tag === 'a') role = 'link';
              else if (el.isContentEditable) role = 'textbox';
            }
            let label = el.getAttribute('aria-label') || '';
            const labelledby = el.getAttribute('aria-labelledby') || '';
            if (!label && labelledby) {
              label = labelledby.split(/\s+/).map(id => {
                const n = document.getElementById(id);
                return n ? (n.innerText || '') : '';
              }).join(' ').trim();
            }
            if (!label) label = el.getAttribute('title') || '';
            if (!label && el.id) {
              const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              if (lab) label = lab.innerText || '';
            }
            // Implicit <label><input> wrapping (radios, checkboxes).
            if (!label && el.closest) {
              const wrap = el.closest('label');
              if (wrap) label = (wrap.innerText || '').trim();
            }
            // fieldset/legend grouping for radios/checkboxes.
            let group = '';
            if (el.closest) {
              const fs = el.closest('fieldset');
              if (fs) {
                const lg = fs.querySelector('legend');
                if (lg) group = (lg.innerText || '').trim();
              }
            }
            if (!label) label = el.getAttribute('placeholder') || el.getAttribute('alt') || el.getAttribute('name') || '';
            if (!label && (role === 'button' || tag === 'button' || tag === 'a'))
              label = (el.innerText || el.value || '').trim();
            const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
            const st = window.getComputedStyle ? window.getComputedStyle(el) : null;
            const hiddenByStyle = !!(st && (st.visibility === 'hidden' || st.opacity === '0'));
            let selector = '';
            if (el.id) selector = '#' + CSS.escape(el.id);
            else if (el.getAttribute('name')) selector = tag + '[name="' + el.getAttribute('name').replace(/"/g, '') + '"]';
            else if (el.getAttribute('data-testid')) selector = '[data-testid="' + el.getAttribute('data-testid').replace(/"/g, '') + '"]';
            else if (el.getAttribute('aria-label')) selector = tag + '[aria-label="' + el.getAttribute('aria-label').replace(/"/g, '') + '"]';
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
            const describedby = el.getAttribute('aria-describedby') || '';
            let errText = '';
            if (describedby) {
              errText = describedby.split(/\s+/).map(id => {
                const n = document.getElementById(id);
                return n ? (n.innerText || '') : '';
              }).join(' ').trim().slice(0, 200);
            }
            let checked = null;
            try {
              if (role === 'checkbox' || role === 'radio' || role === 'switch')
                checked = !!(el.checked ?? el.getAttribute('aria-checked') === 'true');
              if (role === 'combobox' && tag === 'select') checked = null;
            } catch (e) { checked = null; }
            out.push({
              tag, role: role.toLowerCase(), label: (label || '').trim(),
              innerText: ((el.innerText || '').trim() || (label || '').trim()),
              required: !!(el.required || el.getAttribute('aria-required') === 'true'),
              placeholder: el.getAttribute('placeholder') || '',
              name: el.getAttribute('name') || '',
              inputType: type || '',
              group: group || '',
              describedby: describedby || '', errText: errText || '',
              checked: checked,
              disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
              readonly: !!(el.readOnly || el.getAttribute('aria-readonly') === 'true'),
              value: (el.value != null ? String(el.value).slice(0, 200) : ''),
              selector, visible: !!(rect && rect.width > 0 && rect.height > 0) && !hiddenByStyle,
            });
          });
          return out;
        }"""


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
        try:
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            context = await self._browser.new_context(viewport={"width": 1366, "height": 900})
            self._page = await context.new_page()
            self._page.set_default_timeout(self.default_timeout_ms)
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
        from app.api.url_guard import validate_browse_url

        page = self._require_page()
        route = getattr(page, "route", None)
        if route is None:
            return  # test doubles without interception support

        async def _check(route):
            url = route.request.url
            try:
                from urllib.parse import urlparse as _up
                scheme = _up(url).scheme
                if scheme not in ("http", "https", "ws", "wss"):
                    await route.abort()
                    return
                if scheme in ("ws", "wss"):
                    try:
                        await route.continue_()
                    except Exception:
                        pass
                    return
                validate_browse_url(url)
            except ValueError:
                try:
                    await route.abort()
                except Exception:
                    pass
                return
            try:
                await route.continue_()
            except Exception:
                pass

        await page.route("**/*", _check)

    async def stop(self) -> None:
        # Null first, then close: a throwing close must still leave the tool
        # reading stopped, and a failing playwright.stop() must not mask it.
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
                    logger.warning("playwright stop failed during tool teardown")

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
        try:
            from playwright.async_api import TimeoutError as _PWTimeout
        except Exception:
            _PWTimeout = Exception
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self.default_timeout_ms)
        except _PWTimeout:
            logger.warning("navigate timeout for %s", url[:120])
            raise RuntimeError(f"page load timed out: {url[:120]}")
        status = response.status if response else None
        if status is not None and status >= 400:
            raise RuntimeError(f"page returned HTTP {status}")
        try:
            current = page.url or url
        except Exception:
            current = url
        return {"url": current, "http_status": status}

    async def wait_for_load(self, state: str = "load") -> None:
        page = self._require_page()
        try:
            from playwright.async_api import TimeoutError as _PWTimeout
        except Exception:
            _PWTimeout = Exception
        try:
            await page.wait_for_load_state(state, timeout=self.default_timeout_ms)
        except _PWTimeout:
            logger.warning("wait_for_load_state(%s) timed out; continuing with current DOM", state)
        except Exception:
            raise

    async def go_back(self) -> None:
        try:
            await self._require_page().go_back(wait_until="domcontentloaded", timeout=self.default_timeout_ms)
        except Exception:
            logger.warning("go_back failed (empty history?)")

    async def get_title(self) -> str:
        """Proper accessor for the live page title (no private _page reach-in)."""
        return await self._require_page().title()

    # -- perception --

    async def get_accessibility_tree(self) -> Dict[str, Any]:
        """Real interactive-element tree from the live DOM, flattened to the node
        shape the discovery agent parses ({tag, role, label, innerText}).

        Built with page.evaluate over the actual rendered document (labels,
        placeholders, aria attributes, required state) - the same ground truth
        an assistive technology consumes.
        """
        page = self._require_page()
        try:
            # NOTE: this Playwright build's Page.evaluate() takes (expression,
            # arg) only - a timeout kwarg raises TypeError, which broke every
            # discovery (found live: form-fill "discovery failed: RuntimeError").
            nodes = await page.evaluate(TREE_JS)
        except Exception as e:
            raise RuntimeError(f"accessibility tree unreadable: {type(e).__name__}: {str(e)[:120]}")
        return {"tree": nodes or []}

    async def screenshot_b64(self) -> str:
        try:
            data = await self._require_page().screenshot(type="jpeg", quality=70, timeout=15000)
        except Exception as e:
            raise RuntimeError(f"screenshot failed: {type(e).__name__}")
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
                    {"type": "text", "text": (prompt or "")[:2000]},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            "max_tokens": 500,
        }
        import asyncio as _aio
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await _aio.wait_for(client.post(
                    url, json=payload,
                    headers={"Authorization": f"Bearer {settings.nim_api_key}"},
                ), timeout=30)
            except _aio.TimeoutError:
                raise RuntimeError("VLM timed out")
            # A NIM refusal (401/429/5xx - the key rotation and quota spikes
            # this deployment actually hits) is a service-availability fact,
            # not a raw httpx exception: unwrapped, it escaped the route's
            # RuntimeError handler and surfaced as a bare 500.
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"VLM answered {resp.status_code}: "
                    f"{resp.text[:120]}")
            try:
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise RuntimeError(f"bad VLM shape: {type(e).__name__}")
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("bad VLM shape: empty content")
        return {"status": "success", "description": text}
