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

ALL_CASES = TEST_CASES + CONTEXT_TEST_CASES
