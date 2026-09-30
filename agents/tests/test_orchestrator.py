"""Phase 2.1 orchestrator routing (offline: keyword + validation, no LLM needed)."""
from agents.orchestrator import keyword_route, llm_route


def test_keyword_routes_cover_new_agents():
    assert keyword_route("make the font bigger") == "ui_adjuster_agent"
    assert keyword_route("go to checkout now") == "navigation_agent"
    assert keyword_route("update my profile to blind") == "profile_updater_agent"
    assert keyword_route("explain this page simply") == "content_explainer_agent"
    assert keyword_route("something totally random xyz") == "general_agent"


def test_llm_route_falls_back_on_broken_client():
    class Broken:
        def chat(self, messages):
            raise RuntimeError("no network")

    assert llm_route("make font bigger", Broken()) == "ui_adjuster_agent"


def test_llm_route_accepts_valid_name():
    class Fake:
        def chat(self, messages):
            return "navigation_agent"

    assert llm_route("go to checkout", Fake()) == "navigation_agent"


def test_document_beats_generic_summarize():
    """"summarize this doc" contains "summarize": first-match-wins must see
    the document agent first or every doc summary routes to the explainer."""
    assert keyword_route("summarize this doc please") == "document_agent"
    assert keyword_route("summarize this page for me") == "content_explainer_agent"


def test_education_reached_via_unshadowed_keywords():
    assert keyword_route("learn photosynthesis") == "education_agent"


def test_new_specialists_route_without_shadowing_existing():
    assert keyword_route("schedule my doctor appointment for tomorrow") == "scheduler_agent"
    assert keyword_route("remind me to take my medicine at 8pm") == "scheduler_agent"
    assert keyword_route("translate this notice in Hindi please") == "translator_agent"
    assert keyword_route("translate this letter in Tamil") == "translator_agent"
    # Existing priority holds: first-match-wins still reaches incumbents.
    assert keyword_route("make the font bigger") == "ui_adjuster_agent"
    assert keyword_route("summarize this doc please") == "document_agent"
    assert keyword_route("what is the aadhaar number field") == "form_agent"


def test_substring_hijacks_are_gone():
    """Single-word keywords used to match inside unrelated words ('pan' in
    'company', 'form' in 'information', 'read' in 'already')."""
    assert keyword_route("company holidays schedule") == "scheduler_agent"
    assert keyword_route("information about photosynthesis") == "education_agent"
    assert keyword_route("expand the text size") != "form_agent"
    # Whole-word hits still route to form_agent.
    assert keyword_route("fill this form") == "form_agent"
    assert keyword_route("enter my pan number") == "form_agent"


def test_explicit_translate_beats_profile_and_document():
    """'language'/'blind' (profile) and 'document' (document agent) must not
    shadow an explicit translation request."""
    assert keyword_route("what language is this, translate it to hindi") == "translator_agent"
    assert keyword_route("translate this for a blind user") == "translator_agent"
    assert keyword_route("translate this document for me") == "translator_agent"
    # ...while genuine profile/document goals still reach their agents.
    assert keyword_route("update my profile to blind") == "profile_updater_agent"
    assert keyword_route("summarize this doc please") == "document_agent"


def test_profile_language_does_not_hijack_translator():
    """profile_updater's bare 'language' keyword hijacked translator queries;
    the keyword is gone, so language questions with a translate verb route out."""
    assert keyword_route("what language is this, translate it to hindi") == "translator_agent"
    assert keyword_route("update my verbosity settings") == "profile_updater_agent"


def test_navigation_generic_lookup_does_not_hijack():
    """navigation's 'find the'/'where is' hijacked generic lookups; narrowed
    keywords leave those to the web agent while site navigation still routes."""
    assert keyword_route("find the submit button") == "web_agent"
    assert keyword_route("where is the login link") == "web_agent"
    assert keyword_route("go to checkout now") == "navigation_agent"
    assert keyword_route("navigate to the contact form") == "navigation_agent"


def test_translate_my_schedule_reaches_translator():
    """'translate my schedule' matches both translator and scheduler keywords;
    the translator sits first so the explicit translate verb wins."""
    assert keyword_route("translate my schedule to hindi") == "translator_agent"
    assert keyword_route("schedule my doctor appointment for tomorrow") == "scheduler_agent"
