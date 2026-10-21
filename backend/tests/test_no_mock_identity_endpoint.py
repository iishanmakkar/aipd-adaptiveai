"""No callable in the auth module may hand out an identity with no credential.

`get_demo_user()` returned a fresh random-UUID DemoUser for every call and was
referenced by nothing - a mock identity endpoint sitting in the auth module of a
project whose README says there are no mocks left. The DEBUG no-token demo
identity is a separate, deliberately-labelled dev affordance and stays; what must
not come back is a helper anyone can wire into `Depends(...)`.
"""
import inspect

from app.api import auth


def test_mock_identity_helper_is_gone():
    assert not hasattr(auth, "get_demo_user"), (
        "get_demo_user resurrected: it minted a random-UUID user with no "
        "credential behind it and had no caller anywhere in the repo")


def test_no_route_depends_on_a_mock_identity():
    src = inspect.getsource(auth)
    assert "Depends(get_demo_user)" not in src


def test_demo_user_is_still_available_for_the_labeled_debug_path():
    """The class stays on purpose: get_current_user_optional's DEBUG no-token
    branch constructs it, and tests/test_hardening.py asserts that behaviour.
    Removing it would not make the demo path honest - labelling it does."""
    assert hasattr(auth, "DemoUser")
    assert auth.DemoUser().email == "demo@example.com"


def test_shared_demo_identity_is_announced_in_the_log(caplog):
    """Not a comment claim: the warning must actually fire, because per-user
    history and preferences silently keyed to one demo identity look real."""
    import logging

    auth._demo_notice_logged = False
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="adaptiveai.auth"):
        auth.log_demo_identity_in_use("unit test")

    assert any("history and preferences are shared" in r.getMessage()
               for r in caplog.records), "demo identity went unannounced"


def test_demo_identity_notice_is_once_per_process(caplog):
    """A per-request warning would bury every other log line in a busy stack."""
    import logging

    auth._demo_notice_logged = False
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="adaptiveai.auth"):
        auth.log_demo_identity_in_use("first")
        auth.log_demo_identity_in_use("second")
        auth.log_demo_identity_in_use("third")

    announcements = [r for r in caplog.records
                     if "history and preferences are shared" in r.getMessage()]
    assert len(announcements) == 1
