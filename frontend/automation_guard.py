"""Input-isolation guards for the browser automation scripts.

See AUTOMATION_SAFETY.md. These make the "never drive the live desktop" rule
enforceable rather than a convention:

- assert_isolated_browser(): the run must drive a Playwright browser this
  process launched (headless or a dedicated context), so input can only reach
  its own page objects - never the OS foreground window.
- foreground_window_token() / assert_focus_unchanged(): prove the run did not
  steal OS focus. On Windows this reads GetForegroundWindow (a read-only query,
  not synthetic input); elsewhere it degrades to a no-op with a clear reason.
"""
import sys


def assert_isolated_browser(browser) -> None:
    if getattr(browser, "_isolated_launch", None) is not True:
        raise RuntimeError(
            "Refusing to run: browser was not launched by this process as an "
            "isolated instance. Send input only to a Playwright page you started "
            "yourself - never to the OS foreground window (see AUTOMATION_SAFETY.md)."
        )
    if not getattr(browser, "is_connected", lambda: False)():
        raise RuntimeError("Refusing to run: launched browser is not connected.")


def foreground_window_token():
    """Opaque id of the current OS foreground window, or None if unavailable."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None
    return None


def assert_focus_unchanged(before, after, *, allow_change=False) -> None:
    """Fail if the automation changed OS focus (it should never need to).

    Skipped when either token is None (non-Windows / API unavailable) so it
    cannot false-positive on platforms where the check is not meaningful.
    """
    if before is None or after is None:
        return
    if before != after and not allow_change:
        raise RuntimeError(
            f"Automation stole OS focus (foreground window {before:#x} -> "
            f"{after:#x}). Input must be scoped to the launched browser only; "
            "aborting per AUTOMATION_SAFETY.md."
        )
