"""Shared intent classification cases.

Single source of truth for both the offline keyword tests and the live
LLM accuracy runner, so the two can never drift apart.
"""

# (input_text, expected_intent, expected_target_agent)
TEST_CASES = [
    # form_help
    ("What is this field asking for?", "form_help", "form_agent"),
    ("How do I fill the permanent address field?", "form_help", "form_agent"),
    ("What does the Aadhaar number field mean?", "form_help", "form_agent"),
    ("Help me fill this application form", "form_help", "form_agent"),

    # document_help
    ("Summarize this PDF for me", "document_help", "document_agent"),
    ("What does this contract clause mean?", "document_help", "document_agent"),
    ("Extract key points from this document", "document_help", "document_agent"),
    ("Read the terms and conditions to me", "document_help", "document_agent"),

    # web_navigation_help
    ("How do I navigate to the scholarships page?", "web_navigation_help", "web_agent"),
    ("Where is the submit button on this page?", "web_navigation_help", "web_agent"),
    ("Help me find the login link", "web_navigation_help", "web_agent"),
    ("What does this menu item do?", "web_navigation_help", "web_agent"),

    # education_help
    ("Explain photosynthesis in simple terms", "education_help", "education_agent"),
    ("What is machine learning?", "education_help", "education_agent"),
    ("Teach me about the water cycle", "education_help", "education_agent"),
    ("Define Newton's laws of motion", "education_help", "education_agent"),

    # general_query
    ("Hello, how are you?", "general_query", "general_agent"),
    ("What can you help me with?", "general_query", "general_agent"),
    ("Thanks for your help", "general_query", "general_agent"),
    ("Goodbye", "general_query", "general_agent"),
]

# (input_text, expected_intent, expected_target_agent, screen_context)
# Short follow-ups that only make sense against what is on screen.
CONTEXT_TEST_CASES = [
    ("What about this one?", "form_help", "form_agent", "form with fields: Name, Email, Phone"),
    ("And this field?", "form_help", "form_agent", "form with fields: Address, City, Zip"),
    ("Summarize it", "document_help", "document_agent", "PDF document open: rental agreement"),
    ("What does section 4 say?", "document_help", "document_agent", "document showing terms of service"),
    ("Click it", "web_navigation_help", "web_agent", "webpage with Submit Application button"),
    ("Go there", "web_navigation_help", "web_agent", "website navigation menu visible"),
    ("Explain this concept", "education_help", "education_agent", "textbook page about photosynthesis"),
    ("What is this?", "education_help", "education_agent", "educational content about DNA"),
]

# (input_text, expected_intent, expected_target_agent, screen_context)
# Action/inspect phrasing that must reach the LIVE browser - every one of these
# carries the "Live page:" marker, which is the backend's signal that a browser
# session is open for this chat session. The SAME words without a page open
# stay informational (see the web/form cases above): there is nothing real to
# act on, so answering generically is correct there.
LIVE_PAGE_MARKER = "Live page: SwiftRail ticket booking (https://tickets.example.com). "
BROWSER_CASES = [
    ("Where is the submit button on this page?", "browser_inspect", "browser_agent",
     LIVE_PAGE_MARKER + "Book tickets button, Passenger name field"),
    ("What does this field want?", "browser_inspect", "browser_agent",
     LIVE_PAGE_MARKER + "Passenger name field, Email field"),
    ("Find the email field", "browser_inspect", "browser_agent",
     LIVE_PAGE_MARKER + "Passenger name field, Email field"),
    ("Fill in my name as Asha Sharma", "browser_act", "browser_agent",
     LIVE_PAGE_MARKER + "Passenger name field, Email field"),
    ("Click the Book tickets button", "browser_act", "browser_agent",
     LIVE_PAGE_MARKER + "Book tickets button"),
    ("Book 2 seats for me", "browser_act", "browser_agent",
     LIVE_PAGE_MARKER + "Seats dropdown, Book tickets button"),
]

ALL_CASES = (
    [(text, intent, agent, "") for (text, intent, agent) in TEST_CASES]
    + CONTEXT_TEST_CASES
    + BROWSER_CASES
)
