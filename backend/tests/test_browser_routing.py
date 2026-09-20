"""Round 8 chat-routing machinery, offline: URL extraction, confirm/cancel
matching, demotion mapping inputs, inspect composition, fill targeting, and
browser-error mapping. Live Chromium proofs live in the Round 8 fix log."""
import pytest

from app.api import routes_query as rq


def test_extract_url_prefers_message_over_marker():
    assert rq._extract_url("open https://a.example/x please", None) == "https://a.example/x"
    assert rq._extract_url(
        "where is it?",
        "Live page: Demo (https://b.example/y). stuff") == "https://b.example/y"
    assert rq._extract_url("no link here", "plain context") is None
    assert rq._extract_url("", None) is None
    assert rq._extract_url("open data:text/html,<form>x</form> now", None) == "data:text/html,<form>x</form>"


def test_extract_url_never_reads_rag_output():
    """Only user-typed URLs and the page-context marker open pages."""
    assert rq._extract_url("the docs mention example.com often", None) is None


def test_confirm_needs_exact_single_words():
    assert rq._is_confirm("submit")
    assert rq._is_confirm("yes")
    assert rq._is_confirm("  confirm  ")
    assert rq._is_confirm("book it now")
    assert rq._is_confirm("go ahead please")
    assert not rq._is_confirm("yes please tell me more")
    assert not rq._is_confirm("submit what?")
    assert not rq._is_confirm("ok, what about refunds?")


def test_cancel_words():
    assert rq._is_cancel("no, cancel that")
    assert rq._is_cancel("stop")
    assert not rq._is_cancel("submit")


def test_pending_expires():
    import time
    rq._pending["s"] = {"kind": "submit", "created_at": time.time() - 400.0}
    assert rq._get_pending("s") is None
    assert "s" not in rq._pending
    rq._pending["s"] = {"kind": "submit", "created_at": time.time()}
    assert rq._get_pending("s")["kind"] == "submit"
    rq._pending.pop("s", None)


def test_compose_inspect_answer_names_real_position():
    data = {"title": "SwiftRail", "matches": [{
        "label": "Book tickets", "role": "button", "selector": "#book",
        "position": "8 of 8 interactive elements",
        "before": "Seats", "after": "", "submit_action": True}]}
    text = rq._compose_inspect_answer(data, "submit button")
    assert "Book tickets" in text
    assert "8 of 8" in text
    assert "Seats" in text


def test_compose_inspect_answer_empty_is_honest():
    text = rq._compose_inspect_answer({"title": "T", "matches": []}, "zzz")
    assert "nothing" in text and "zzz" in text


def test_fill_targets_only_fillable_controls():
    nodes = [
        {"tag": "input", "label": "Name", "selector": "#n", "type": "text"},
        {"tag": "textarea", "label": "Notes", "selector": "#t", "type": ""},
        {"tag": "select", "label": "Seats", "selector": "#s", "type": ""},
        {"tag": "input", "label": "Go", "selector": "#g", "type": "submit"},
        {"tag": "input", "label": "Agree", "selector": "#c", "type": "checkbox"},
        {"tag": "button", "label": "Clear", "selector": "#b", "type": "button"},
        {"tag": "input", "label": "", "selector": "#u", "type": "text"},
    ]
    got = [n["label"] for n in rq._fill_targets(nodes)]
    assert got == ["Name", "Notes", "Seats"]


def test_browser_error_mapping_is_honest():
    import httpx
    def err(code, detail="blocked"):
        req = httpx.Request("POST", "http://x/")
        resp = httpx.Response(code, json={"detail": detail}, request=req)
        return httpx.HTTPStatusError("e", request=req, response=resp)
    assert rq._browser_error_detail(err(423, "captcha here")) == (423, "captcha here")
    assert rq._browser_error_detail(err(429))[0] == 429
    code, msg = rq._browser_error_detail(RuntimeError("boom"))
    assert code == 502 and "RuntimeError" in msg
