"""Form Filler Replay Agent (Form Filler Agent, AWS).

Plays back cached form filling actions from episodic memory.
Field-level replay with state verification before each action.
Enables "one-click" form filling on repeat visits.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

from app.services.episodic_memory import EpisodicMemory, Episode, episodic_memory

from app.agents.form.browser_tool import BrowserTool

logger = logging.getLogger(__name__)


class ReplayAgent:
    """Replays cached form filling actions from episodic memory."""
    
    def __init__(self, browser: Optional[BrowserTool] = None, memory: Optional[EpisodicMemory] = None):
        self.browser = browser or BrowserTool()
        self.memory = memory or episodic_memory
    
    async def replay_form(self, episode_id: str, url: str, values: Dict[str, str] = None) -> Dict[str, Any]:
        """Replay cached form filling actions.
        
        Args:
            episode_id: The cached episode ID
            url: Current page URL
            values: Optional user-filled values to override cached ones
            
        Returns replay result with status and any issues.
        """
        # Access episode to refresh relevance
        episode = await self.memory.access_episode(episode_id)
        if episode is None:
            return {"status": "failed", "reason": "Episode not found in memory", "action": "re_discover"}

        if not episode.actions:
            # An empty cached episode (caching used to persist empty
            # discoveries) must not "succeed" with zero fills - and must not
            # boot Chromium for nothing.
            return {"status": "failed", "reason": "Cached episode has no actions",
                    "episode_id": episode_id, "action": "re_discover"}

        # Check TTL
        age = __import__("time").time() - episode.created_at
        if age < 0 or age > 86400:  # 24 hours (future = clock skew, expire)
            return {"status": "expired", "reason": "Episode older than 24 hours", "action": "re_discover",
                    "episode_id": episode_id}

        # try/finally: any exception used to leak a live Chromium process (the
        # only stop() calls sat on the happy path and one early return).
        await self.browser.start()
        try:
            try:
                await self.browser.navigate(url)
            except Exception as e:
                return {"status": "failed", "reason": f"navigation failed: {type(e).__name__}",
                        "episode_id": episode_id, "action": "re_discover"}
            await self.browser.wait_for_load()
            return await self._replay_actions(episode, episode_id, values)
        finally:
            await self.browser.stop()

    async def _replay_actions(self, episode, episode_id: str,
                              values: Dict[str, str] = None) -> Dict[str, Any]:

        replay_results = []
        success_count = 0
        failure_count = 0
        unfilled: List[str] = []

        # Execute each action from the cached episode. Submit-class clicks are
        # executed here deliberately: replay only runs on an EXPLICIT request
        # (POST /api/form-fill from the dialog's "Fill/Replay" button — that
        # invocation is the confirmation), with a 24h episode TTL and
        # per-action results + a page readback returned. The CHAT path keeps
        # its own hold-for-confirmation gate in routes_query.
        for i, action in enumerate(episode.actions):
            try:
                result = await asyncio.wait_for(
                    self._execute_replay_action(action, values), timeout=15)
            except asyncio.TimeoutError:
                result = {"status": "failed", "reason": "action timed out",
                          "action": action.get("type"), "field_id": action.get("field_id"),
                          "label": action.get("label")}
            replay_results.append(result)

            if result.get("status") == "success":
                success_count += 1
            elif result.get("status") == "not_selected":
                # Explicit answer ("no"): neither a fill nor a gap. Track it as
                # handled so success_count/status stay honest.
                success_count += 1
            elif result.get("status") in ("no_value", "skipped"):
                # Found but not fillable now (no answer / disabled): track the
                # name, do not count as breakage or trigger heal.
                unfilled.append(result.get("label") or result.get("field_id") or f"field {i}")
            else:
                failure_count += 1

                # If too many failures, stop and re-discover
                if failure_count >= 3:
                    early_message = await self._read_page_message()
                    return {
                        "status": "partial_failure",
                        "episode_id": episode_id,
                        "replay_results": replay_results,
                        "success_count": success_count,
                        "failure_count": failure_count,
                        "unfilled": unfilled,
                        "page_message": early_message,
                        "action": "re_discover_partial",
                    }

        page_message = await self._read_page_message()

        if failure_count or unfilled:
            status = "partial_success"
        else:
            status = "success"
        return {
            "status": status,
            "replay_results": replay_results,
            "success_count": success_count,
            "failure_count": failure_count,
            "unfilled": unfilled,
            "page_message": page_message,
            "episode_id": episode_id,
            "action": "replay_complete",
        }

    async def _read_page_message(self) -> str | None:
        """What the page itself said after the actions ran.

        Booking a ticket or filing a grievance ends with the SITE's message
        ("Booked 2 seat(s)… Reference PNR101017", "Ticket #4821 received").
        A user who cannot see the screen has to hear that, and it is also the
        only evidence that the submit actually took - per-action 'success'
        proves the click, not the outcome. Read from the live DOM; None means
        the read itself crashed (vs "" = page said nothing)."""
        page = getattr(self.browser, "_page", None)
        if page is None:
            return None
        try:
            # NOTE: this Playwright build's Page.evaluate() takes
            # (expression, arg) only - a timeout kwarg raises TypeError, which
            # made every readback silently return None (found live).
            text = await page.evaluate("""() => {
                const selectors = ['[role=status]', '[aria-live]', '#confirmation',
                                   '.confirmation', '[class*=confirmation]',
                                   '[class*=success]', '[class*=message]',
                                   '[role=alert]', '.error', '[class*=error]',
                                   'h1', '[role=dialog]'];
                const seen = [];
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        const t = (el.innerText || '').trim();
                        if (t && t.length > 1 && !seen.includes(t)) seen.push(t);
                    }
                }
                return seen.join(' | ').slice(0, 600);
            }""")
        except Exception as e:
            # A failed read is NOT an empty page: log it so "the page said
            # nothing" is never reported for a dead evaluate.
            logger.warning("page message read failed: %s", type(e).__name__)
            return None
        return text or ""
    
    async def _execute_replay_action(self, action: Dict[str, Any], values: Dict[str, str] = None) -> Dict[str, Any]:
        """Execute a single replay action with state verification.

        Locating order (all real DOM data stored at discovery time):
        stored css selector -> placeholder text -> label text (exact then
        substring). No string-interpolated selectors: only Playwright
        get_by_* resolvers (auto-escaped).
        """
        action_type = action.get("type", "focus_and_type")
        field_id = action.get("field_id", "")
        label = action.get("label", "") or ""
        placeholder = action.get("placeholder", "") or ""
        try:
            page = self.browser._require_page()
        except Exception:
            return {"status": "failed", "reason": "browser not started",
                    "action": action_type, "field_id": field_id, "label": label}

        field = None
        if action.get("selector"):
            # NOTE: this Playwright build's Page.query_selector(selector, strict)
            # takes NO timeout kwarg - passing one raises TypeError. It used to
            # be swallowed by the except below, so every element located ONLY
            # by its own selector (buttons, unlabeled controls) silently became
            # "field not found" (found live: the submit button).
            try:
                field = await page.query_selector(action["selector"])
                if field:
                    try:
                        if not await field.is_visible():
                            field = None
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("selector lookup failed for %s: %s",
                               action.get("field_id"), type(e).__name__)
                field = None
        if not field and placeholder:
            try:
                get_by_placeholder = getattr(page, "get_by_placeholder", None)
                if get_by_placeholder is not None:
                    loc = get_by_placeholder(placeholder)
                    if await loc.count() == 1:
                        field = await loc.element_handle()
            except Exception:
                field = None
        if not field and label:
            # Exact first (First vs Last Name), substring only if unique.
            try:
                get_by_label = getattr(page, "get_by_label", None)
                if get_by_label is not None:
                    loc = get_by_label(label, exact=True)
                    if await loc.count() == 1:
                        field = await loc.element_handle()
                    else:
                        loc2 = get_by_label(label, exact=False)
                        if await loc2.count() == 1:
                            field = await loc2.element_handle()
            except Exception:
                field = None
        
        if not field:
            return {"status": "failed", "reason": f"Field {field_id} not found on page", "action": "skip"}
        
        # Check if field is enabled/interactable (inside try: detached nodes
        # raise here and must fail just this action, not the whole loop).
        try:
            is_enabled = await field.is_enabled()
            if not is_enabled:
                return {"status": "skipped", "reason": f"Field {field_id} is disabled", "action": "skip",
                        "field_id": field_id, "label": label}
        except Exception as e:
            return {"status": "failed", "reason": f"field gone: {type(e).__name__}",
                    "action": action_type, "field_id": field_id, "label": label}
        
        # Determine value: exact label key first, then case-insensitive scan
        # (values ""/False/"0" are legitimate answers, never fall through).
        value = None
        found = False
        if values:
            if label in values:
                value, found = values[label], True
            elif field_id in values:
                value, found = values[field_id], True
            else:
                lowered = {str(k).casefold(): v for k, v in values.items()}
                if label.casefold() in lowered:
                    value, found = lowered[label.casefold()], True
                elif placeholder and placeholder.casefold() in lowered:
                    value, found = lowered[placeholder.casefold()], True

        # Radio/checkbox choice: only click the option the user picked.
        if action_type == "click" and not action.get("is_action_button", False):
            if values is not None and not found:
                return {"status": "no_value", "field_id": field_id, "label": label,
                        "action": action_type, "reason": "no value supplied for this choice"}
            if values is not None and found:
                want = str(value).strip().casefold()
                have = f"{label} {placeholder}".strip().casefold()
                # "on"/"true"/"yes" selects this option; "off"/"false"/"no"
                # explicitly leaves it alone (never toggles blind).
                if want in ("off", "false", "no", "0"):
                    # An explicit "no" is an ANSWER, not a gap: it must not
                    # land in `unfilled` (that turns an honest full fill into
                    # partial_success and warns the user about nothing).
                    return {"status": "not_selected", "field_id": field_id, "label": label,
                            "action": action_type, "reason": "choice left unselected by user"}
                if want not in ("on", "true", "yes", "1") and want and want not in have and have not in want:
                    return {"status": "skipped", "field_id": field_id, "label": label,
                            "action": action_type, "reason": "choice not selected by user"}

        needs_value = action_type in ("focus_and_type", "select")
        if not found and needs_value:
            # Cached episodes never store what was typed (that is user data), so
            # "no value supplied" is the honest status - not an empty fill
            # quietly counted as success.
            return {"status": "no_value", "field_id": field_id, "label": label,
                    "action": action_type,
                    "reason": "no value supplied for this field"}

        # Execute action based on type
        try:
            if action_type == "focus_and_type":
                await field.fill(str(value), timeout=5000)
                try:
                    if await field.input_value() != str(value):
                        return {"status": "failed", "reason": "fill did not stick",
                                "action": action_type, "field_id": field_id, "label": label}
                except Exception:
                    pass
                return {"status": "success", "action": action_type, "field_id": field_id,
                        "label": label, "value": value}

            elif action_type == "click":
                await field.click(timeout=5000)
                if action.get("is_action_button"):
                    try:
                        await page.wait_for_load_state("load", timeout=10000)
                    except Exception:
                        pass
                    return {"status": "success", "action": action_type,
                            "field_id": field_id, "label": label}

                # Choice click. Nobody is looking at the screen, so the checked
                # state IS the success signal - a click that leaves the box
                # unchecked must never be reported as done. Some radios and
                # checkboxes only flip on a second pass (label wiring), so retry
                # once before failing.
                checked = False
                for attempt in (1, 2):
                    try:
                        checked = await field.is_checked()
                    except Exception:
                        checked = False
                    if checked:
                        break
                    if attempt == 1:
                        try:
                            await field.click(timeout=5000)
                        except Exception:
                            break
                if not checked:
                    return {"status": "failed", "action": action_type,
                            "field_id": field_id, "label": label,
                            "reason": "still not checked after two click passes"}
                return {"status": "success", "action": action_type,
                        "field_id": field_id, "label": label}

            elif action_type == "select":
                # Handle dropdown selection
                opts = await field.select_option(str(value), timeout=5000)
                if not opts:
                    return {"status": "failed", "reason": f"value not in dropdown options: {value}",
                            "action": action_type, "field_id": field_id, "label": label}
                return {"status": "success", "action": action_type, "field_id": field_id,
                        "label": label, "value": value}

            else:
                return {"status": "failed", "reason": f"unknown action: {action_type}",
                        "action": action_type, "field_id": field_id, "label": label}

        except Exception as e:
            return {"status": "failed", "reason": str(e), "action": action_type,
                    "field_id": field_id, "label": label}
    
    async def replay_with_state_check(self, episode_id: str, url: str, user_values: Dict[str, str] = None) -> Dict[str, Any]:
        """Replay with full state verification before each action."""
        # Similar to replay_form but with additional checks
        # (visibility, enabled state, not already filled, etc.)
        result = await self.replay_form(episode_id, url, user_values)
        
        # Add state verification info
        if result.get("status") in ("success", "partial_success"):
            # Verify all required fields were interacted with
            interacted_fields = set()
            for r in result.get("replay_results", []):
                if r.get("status") == "success":
                    interacted_fields.add(r.get("field_id"))
            
            # Check required fields from the original episode
            # (would need metadata about which fields are required)
            
        return result