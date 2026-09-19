"""Browser-agent tools backed by the REAL Playwright driver.

Each tool executes against a live Chromium page via Driver. Results report what
actually happened (HTTP status, readback values, real text). No canned outputs.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import os

from app.tools.driver import Driver


class BaseTool(ABC):
    name: str = "base_tool"

    def __init__(self, driver: Optional[Driver] = None):
        self.driver = driver or Driver()

    @abstractmethod
    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        pass

    def validate_kwargs(self, required: list, kwargs: dict) -> bool:
        missing = [k for k in required if k not in kwargs]
        if missing:
            return False, f"Missing required parameters: {missing}"
        return True, ""


class BrowserTool(BaseTool):
    """Navigate / click / fill / extract on a live page."""

    name = "browser"

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        if action == "navigate":
            ok, msg = self.validate_kwargs(["url"], kwargs)
            if not ok:
                return {"status": "error", "detail": msg}
            nav = await self.driver.navigate(kwargs["url"])
            return {"action": action, "status": "completed", **nav}
        if action == "click":
            return {"action": action, **await self.driver.click(kwargs.get("selector", ""))}
        if action in ("fill", "type"):
            return {"action": action, **await self.driver.fill(
                kwargs.get("selector", ""), kwargs.get("value", ""))}
        if action == "extract":
            return {"action": action, **await self.driver.extract_text(kwargs.get("selector"))}
        return {"status": "error", "detail": f"unknown browser action: {action}"}


class AccessibilityTreeTool(BaseTool):
    """Snapshot the live DOM (labels, roles, selectors)."""

    name = "accessibility_tree"

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        if action not in ("extract", "query", "filter"):
            return {"status": "error", "detail": f"unknown accessibility action: {action}"}
        snap = await self.driver.snapshot()
        nodes = snap.get("nodes", [])
        roles = kwargs.get("roles")
        if roles:
            roles = {r.lower() for r in roles}
            nodes = [n for n in nodes if n.get("type", "") in roles or n.get("tag") in roles]
        return {"action": action, "status": "completed", "title": snap.get("title"),
                "url": snap.get("url"), "node_count": len(nodes), "nodes": nodes[:100]}


class VLMAnalysisTool(BaseTool):
    """Describe a live screenshot through the real NIM vision model."""

    name = "vlm_analysis"

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        if action not in ("describe", "analyze", "extract"):
            return {"status": "error", "detail": f"unknown vlm action: {action}"}
        api_key = os.getenv("NIM_API_KEY", "")
        if not api_key:
            return {"status": "error",
                    "detail": "VLM not configured: NIM_API_KEY is missing (no canned description exists)."}
        import httpx
        base_url = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
        model = os.getenv("NIM_MODEL", "meta/llama-3.2-11b-vision-instruct")
        image_b64 = await self.driver.screenshot_b64()
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": kwargs.get("prompt") or kwargs.get("context")
                     or "Describe this page for a visually impaired user. Be concise but thorough."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            "max_tokens": 500,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload,
                                     headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
        return {"action": action, "status": "completed", "details": text}


class FormFillingTool(BaseTool):
    """Fill live form fields by selector with same-page readback verification."""

    name = "form_filling"

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        if action in ("fill", "repair", "discover_and_fill"):
            fields = kwargs.get("fields") or []
            if kwargs.get("field") and kwargs.get("value") is not None:
                fields = [{"selector": kwargs["field"], "value": kwargs["value"]}]
            results = []
            for f in fields:
                results.append(await self.driver.fill(f.get("selector", ""), f.get("value", "")))
            ok = sum(1 for r in results if r.get("status") == "completed")
            return {"action": action,
                    "status": "completed" if ok == len(results) and results else "error",
                    "filled": ok, "total": len(results), "results": results}
        if action == "cache":
            return {"status": "error",
                    "detail": "pattern caching lives in the backend episodic-memory service, not here."}
        return {"status": "error", "detail": f"unknown form action: {action}"}
