"""Round 9 monitor plumbing, offline: voice-command matching semantics.
Client contracts live in test_clients.py (shared capture fixture); live
monitor proofs live in the Round 9 log."""
from app.api import routes_query as rq


# ---- voice-command matching -------------------------------------------------

def test_watch_start_phrases():
    for phrase in ("watch my screen", "Watch my screen please",
                   "start watching the page", "monitor this page for me",
                   "keep an eye on this page"):
        assert rq._watch_command(phrase) == "start"


def test_watch_stop_phrases_win_over_cancel_word():
    # "stop watching my screen" is a monitor command, not a proposal cancel.
    assert rq._watch_command("stop watching my screen") == "stop"
    assert rq._watch_command("Stop monitoring my screen") == "stop"
    assert rq._watch_command("turn off monitoring") == "stop"


def test_bare_stop_is_not_a_watch_command():
    # Bare "stop" must keep its Round 8 meaning (cancel held proposal).
    assert rq._watch_command("stop") is None
    assert rq._watch_command("submit") is None
    assert rq._watch_command("what is an aadhaar number") is None


def test_unrelated_sentences_do_not_match():
    assert rq._watch_command("i stopped by the bank yesterday") is None
    assert rq._watch_command("which seat should i book") is None


# ---- slot-fill values are data, not commands (found live) --------------------

def test_free_text_values_are_not_cancel():
    """A value containing a cancel WORD must reach the field, not cancel."""
    assert not rq._is_exact_cancel("Street light not working near block 4")
    assert not rq._is_exact_cancel("The notification never arrived")
    assert not rq._is_exact_cancel("No response from the office for 2 weeks")
    assert not rq._is_exact_cancel("abortion clinic signposting")  # substring safety


def test_exact_cancel_phrases_still_cancel_fills():
    assert rq._is_exact_cancel("cancel")
    assert rq._is_exact_cancel("Cancel that.")
    assert rq._is_exact_cancel("never mind")
    assert rq._is_exact_cancel("stop")


def test_held_submits_keep_the_loose_cancel_check():
    """A held submit/navigate may be cancelled mid-sentence."""
    assert rq._is_cancel("no, cancel that")
    assert rq._is_cancel("actually stop")
