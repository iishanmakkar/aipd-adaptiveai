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
from typing import Any, Dict, List, Optional

from app.agents.form.browser_tool import BrowserTool

logger = logging.getLogger(__name__)


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
        await self.browser.start()
        await self.browser.navigate(url)
        await self.browser.wait_for_load()
        
        # Get accessibility tree
        tree_result = await self.browser.get_accessibility_tree()
        tree = tree_result.get("tree", [])
        
        # Real vision description of the live page (raises if VLM unconfigured).
        vlm_result = await self.browser.get_vlm_description(self.vlm_prompt)
        
        # Parse fields from accessibility tree
        fields = self._parse_fields_from_tree(tree)
        
        # Cache the discovery
        discovery_id = self._generate_discovery_id(url, tree, fields)
        
        result = {
            "discovery_id": discovery_id,
            "url": url,
            "fields": fields,
            "tree_snapshot": tree[:50],  # First 50 nodes
            "vlm_description": vlm_result.get("description", vlm_result.get("status", "")),
            "iframe_depth": iframe_depth,
            "status": "success",
        }
        
        await self.browser.stop()
        return result
    
    def _parse_fields_from_tree(self, tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse form fields from accessibility tree nodes."""
        fields = []
        
        for node in tree:
            tag = node.get("tag", "")
            role = node.get("role", "")
            label = node.get("label", "")
            inner_text = node.get("innerText", "")
            
            # Look for interactive form elements
            if role in ("textbox", "search", "textarea", "combobox", "listbox"):
                field = {
                    "field_id": hashlib.sha256(f"{tag}{label}".encode()).hexdigest()[:12],
                    "type": role,
                    "label": label or inner_text[:100],
                    "tag": tag,
                    "aria_role": role,
                    "selector": node.get("selector", ""),
                    "placeholder": node.get("placeholder", ""),
                    "required": node.get("required", False) or "required" in label.lower(),
                    "description": f"{tag} {label}".strip(),
                }
                fields.append(field)

            # Radios / checkboxes are choices, not text: click them.
            elif role in ("radio", "checkbox"):
                field = {
                    "field_id": hashlib.sha256(f"{tag}{label}".encode()).hexdigest()[:12],
                    "type": role,
                    "label": label or inner_text[:100] or role,
                    "tag": tag,
                    "aria_role": role,
                    "selector": node.get("selector", ""),
                    "is_action_button": False,
                    "description": f"{tag} {role} - {label}".strip(),
                }
                fields.append(field)

            # Search buttons
            elif role in ("button", "submit", "reset"):
                if any(kw in (label or "").lower() for kw in ["submit", "send", "search", "go", "book", "pay", "confirm", "continue", "next", "login", "sign"]):
                    field = {
                        "field_id": hashlib.sha256(f"{tag}{label}".encode()).hexdigest()[:12],
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
        hash_input = f"{url}|{len(tree)}|{len(fields)}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    async def discover_iframes(self, max_iframes: int = 5) -> List[Dict[str, Any]]:
        """Discover forms in iframes on the page."""
        iframe_results = []
        
        iframes = await self.browser._page.query_selector_all("iframe")
        for i, iframe in enumerate(iframes[:max_iframes]):
            try:
                await iframe.focus()
                await self.browser.navigate(iframe.get_attribute("src") or "about:blank")
                await self.browser.wait_for_load()
                
                result = await self.discover_form(iframe.get_attribute("src") or "")
                result["iframe_index"] = i
                iframe_results.append(result)
                
                # Go back to main page
                await self.browser.go_back()
                await self.browser.wait_for_load()
            except Exception as e:
                logger.warning(f"IFrame {i} discovery failed: {e}")
        
        return iframe_results