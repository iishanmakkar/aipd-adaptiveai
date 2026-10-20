"""Shared browser-audit helper: get past the login screen.

The app sits behind real authentication now (the UI holds a bearer JWT and the
backend refuses /api/* without one unless it is in DEBUG demo mode), so an
automated walk-through has to sign in the way a user does. This creates a
throwaway account through the same form - no back door, no seeded fixture.
"""
import secrets


def sign_up_and_in(page, password="audit-pass-123", email=None):
    email = email or f"audit-{secrets.token_hex(4)}@example.com"
    page.get_by_role("button", name="Create account", exact=True).click()
    page.get_by_label("Email address").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Create account and continue").click()
    page.wait_for_selector("div[role='application']", timeout=60000)
    return email


def utf8_console():
    """Windows consoles default to cp1252, which cannot encode the emoji used
    in suggestion chips and answer badges - without this the audit dies
    mid-run on a print of perfectly good page text (found live, twice)."""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
