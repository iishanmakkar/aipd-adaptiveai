"""Form Filler Discovery Agent (Form Filler Agent, Fantoma).

Discovers forms on a page using ARIA tree + VLM vision.
Caches field locations with embeddings for subsequent replays.
Supports iframe scanning (up to 5 iframes deep).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.form.browser_tool import BrowserTool

logger = logging.getLogger(__name__)


# Submit-class button words. Whole-word matching only: bare `in` matched
# "go" inside "Forgot"/"Logout"/"Google" and "sign" inside "Signal", caching
# the wrong buttons - and replay EXECUTES cached clicks, so a login page
# replay once clicked "Forgot password" and navigated away from the form.
_ACTION_BUTTON_WORDS = (
    "submit", "send", "search", "go", "book", "pay", "confirm", "continue",
    "next", "login", "sign",
)


def _is_action_button(label: str, input_type: str = "") -> bool:
    """A real submit control, or a button whose label names a submit action."""
    if input_type == "submit":
        return True
    lowered = (label or "").lower()
    return any(re.search(r"\b" + re.escape(kw) + r"\b", lowered)
               for kw in _ACTION_BUTTON_WORDS)


def _field_id(tag: str, label: str, node: Dict[str, Any]) -> str:
    """Stable id for one control. Keyed by tag + label + placeholder +
    selector: tag+label alone collided across same-labeled fields (two "Yes"
    radios, several unlabeled inputs), making overrides, healing and
    diagnostics unable to tell them apart."""
    return hashlib.sha256(
        f"{tag}|{label}|{node.get('placeholder', '')}|{node.get('selector', '')}"
        .encode()).hexdigest()[:12]


class DiscoveryAgent:
    """Discovers forms on a page using dual-layer perception."""
    
    def __init__(self, browser: Optional[BrowserTool] = None, vlm_prompt: str = None):
        # Real Chromium by default - never a simulated page.
        self.browser = browser or BrowserTool()
        self.vlm_prompt = vlm_prompt or "Describe this page for a visually impaired user. Identify form fields, buttons, layout, and any visible text. Be concise but thorough."
    
    async def discover_form(self, url: str, iframe_depth: int = 5) -> Dict[str, Any]:
        """Discover all forms on a page.

        Returns form discoveries with field information,
        cached with embeddings for replay.
        """
        # try/finally: any exception (VLM unconfigured, bad page, upstream
        # error) used to leak a live Chromium + Playwright process per call —
        # routes_formfill builds a fresh BrowserTool per request.
        await self.browser.start()
        try:
            await self.browser.navigate(url)
            await self.browser.wait_for_load()

            # Get accessibility tree
            tree_result = await self.browser.get_accessibility_tree()
            tree = tree_result.get("tree", [])

            # Vision is best-effort enrichment: a missing key/offline NIM must
            # not discard a good tree (blind users still get every field).
            try:
                vlm_result = await self.browser.get_vlm_description(self.vlm_prompt)
                vlm_desc = vlm_result.get("description", "")
            except Exception as e:
                logger.warning("VLM enrichment failed, continuing with tree only: %s", type(e).__name__)
                vlm_desc = ""

            # Parse fields from accessibility tree
            fields = self._parse_fields_from_tree(tree)
            if iframe_depth and iframe_depth > 1:
                try:
                    for fr in await self.discover_iframes(max_iframes=5):
                        for f in fr.get("fields", []):
                            f["iframe_index"] = fr.get("iframe_index")
                            fields.append(f)
                except Exception:
                    pass

            # Cache the discovery
            discovery_id = self._generate_discovery_id(url, tree, fields)

            result = {
                "discovery_id": discovery_id,
                "url": url,
                "fields": fields,
                "tree_snapshot": tree[:50],  # First 50 nodes
                "vlm_description": vlm_desc,
                "iframe_depth": iframe_depth,
                # An empty field list is NOT a success: the page may not have
                # rendered yet (SPA), or this may not be a form page at all.
                # Callers must not cache or "successfully replay" this.
                "status": "success" if fields else "no_fields",
            }
            return result
        finally:
            await self.browser.stop()
    
    def _parse_fields_from_tree(self, tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse form fields from accessibility tree nodes."""
        fields = []
        
        for node in tree:
            tag = node.get("tag", "")
            role = node.get("role", "")
            label = node.get("label", "")
            inner_text = node.get("innerText", "")
            
            # Look for interactive form elements
            if role in ("textbox", "search", "searchbox", "textarea", "combobox", "listbox"):
                field = {
                    "field_id": _field_id(tag, label, node),
                    "type": role,
                    "label": label or inner_text[:100],
                    "tag": tag,
                    "aria_role": role,
                    "input_type": node.get("inputType", ""),
                    "selector": node.get("selector", ""),
                    "placeholder": node.get("placeholder", ""),
                    "name": node.get("name", ""),
                    "group": node.get("group", ""),
                    "required": node.get("required", False) or bool(re.search(r"\brequired\b", label, re.I)),
                    "disabled": node.get("disabled", False),
                    "description": f"{tag} {label}".strip(),
                }
                fields.append(field)

            # Radios / checkboxes / switches are choices, not text: click them.
            elif role in ("radio", "checkbox", "switch"):
                field = {
                    "field_id": _field_id(tag, label, node),
                    "type": role,
                    "label": label or inner_text[:100] or node.get("group", "") or role,
                    "tag": tag,
                    "aria_role": role,
                    "selector": node.get("selector", ""),
                    "group": node.get("group", ""),
                    "checked": node.get("checked"),
                    "is_action_button": False,
                    "description": f"{tag} {role} - {label}".strip(),
                }
                fields.append(field)

            # Search buttons
            elif role in ("button", "submit", "reset", "link"):
                if role == "link" and not _is_action_button(label, node.get("inputType", "")):
                    continue
                if _is_action_button(label, node.get("inputType", "")) or role in ("submit", "reset"):
                    field = {
                        "field_id": _field_id(tag, label, node),
                        "type": role,
                        "label": label or "Submit",
                        "tag": tag,
                        "aria_role": role,
                        "selector": node.get("selector", ""),
                        "is_action_button": True,
                        "description": f"{tag} - {label}".strip(),
                    }
                    fields.append(field)
        
        return fields
    
    def _generate_discovery_id(self, url: str, tree: List[Dict], fields: List[Dict]) -> str:
        """Generate a unique discovery ID for caching."""
        import json as _json
        try:
            sig = _json.dumps([(f.get("label"), f.get("selector")) for f in fields], sort_keys=True)
        except Exception:
            sig = str(len(fields))
        hash_input = f"{url}|{sig}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    async def discover_iframes(self, max_iframes: int = 5) -> List[Dict[str, Any]]:
        """Discover forms in iframes on the page.

        Each iframe gets its own browser lifecycle via discover_form (which
        owns start/stop): there is nothing to navigate back to between
        iterations. The old version called go_back() on the shared browser
        AFTER discover_form had stopped it, so every iframe past the first
        failed identically and was swallowed by the except below.
        """
        from app.api.url_guard import validate_browse_url

        page = getattr(self.browser, "_page", None)
        if page is None:
            return []
        try:
            iframes = await page.query_selector_all("iframe")
        except Exception:
            return []
        try:
            page_url = page.url or ""
        except Exception:
            page_url = ""
        from urllib.parse import urljoin as _urljoin
        srcs = []
        for iframe in iframes[:max_iframes]:
            try:
                src = await iframe.get_attribute("src") or ""
                if not src or src == "about:blank" or src.startswith(("javascript:", "data:")):
                    continue
                src = _urljoin(page_url, src) if page_url else src
                try:
                    validate_browse_url(src)
                except ValueError:
                    continue
                srcs.append(src)
            except Exception:
                continue
        iframe_results = []
        for i, src in enumerate(srcs):
            try:
                # Fresh driver per iframe: discover_form owns start/stop.
                from app.agents.form.browser_tool import BrowserTool as _BT
                result = await DiscoveryAgent(_BT()).discover_form(src, iframe_depth=1)
                result["iframe_index"] = i
                iframe_results.append(result)
            except Exception as e:
                logger.warning(f"IFrame {i} discovery failed: {e}")

        return iframe_results