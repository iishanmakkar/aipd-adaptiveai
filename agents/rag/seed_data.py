SEED_DOCUMENTS = [
    # Form-field glossary (10 entries)
    {
        "id": "form_permanent_address",
        "text": "Permanent Address: This is your official residential address as listed on government-issued ID proof (Aadhaar, Voter ID, Passport). It is NOT your current temporary address or hostel address. Used for official correspondence and verification.",
        "metadata": {"category": "form_glossary", "field": "permanent_address", "tags": ["address", "id_proof", "official"]}
    },
    {
        "id": "form_aadhar_number",
        "text": "Aadhaar Number: A 12-digit unique identification number issued by UIDAI. Enter all 12 digits without spaces or dashes. This is used for identity verification and linking government services. Keep it confidential.",
        "metadata": {"category": "form_glossary", "field": "aadhar_number", "tags": ["identity", "uidai", "12_digit"]}
    },
    {
        "id": "form_pan_number",
        "text": "PAN Number: A 10-character alphanumeric code (format: ABCDE1234F) issued by Income Tax Department. First 5 characters are letters, next 4 are numbers, last is a letter. Required for financial transactions and tax filing.",
        "metadata": {"category": "form_glossary", "field": "pan_number", "tags": ["tax", "income_tax", "alphanumeric"]}
    },
    {
        "id": "form_date_of_birth",
        "text": "Date of Birth: Enter your birth date in DD/MM/YYYY format (day/month/year). Example: 15/08/1995. This must match your birth certificate and other official documents. Used for age verification and eligibility checks.",
        "metadata": {"category": "form_glossary", "field": "date_of_birth", "tags": ["date", "format", "verification"]}
    },
    {
        "id": "form_guardian_name",
        "text": "Guardian Name: Full legal name of your parent or legal guardian. If father is guardian, enter father's full name. If mother, enter mother's name. For married women, this may still be father's name depending on form requirements. Check form instructions.",
        "metadata": {"category": "form_glossary", "field": "guardian_name", "tags": ["parent", "legal_guardian", "family"]}
    },
    {
        "id": "form_annual_income",
        "text": "Annual Income: Total yearly income from all sources (salary, business, investments, etc.) in Indian Rupees. Enter numeric value only (e.g., 500000 for 5 lakh). Used for scholarship eligibility, fee concessions, and economic category determination.",
        "metadata": {"category": "form_glossary", "field": "annual_income", "tags": ["income", "scholarship", "fee_concession"]}
    },
    {
        "id": "form_caste_category",
        "text": "Caste Category: Select your official caste category as per government records: General, OBC (Other Backward Classes), SC (Scheduled Caste), ST (Scheduled Tribe), or EWS (Economically Weaker Section). Must match your caste certificate. Determines reservation benefits.",
        "metadata": {"category": "form_glossary", "field": "caste_category", "tags": ["reservation", "caste_certificate", "government"]}
    },
    {
        "id": "form_disability_certificate",
        "text": "Disability Certificate Number: Unique number from your disability certificate issued by a government medical board. Format varies by state. Enter the certificate number exactly as shown. Used for disability quota, concessions, and accessibility accommodations.",
        "metadata": {"category": "form_glossary", "field": "disability_certificate", "tags": ["disability", "medical_board", "quota"]}
    },
    {
        "id": "form_bank_account",
        "text": "Bank Account Details: Enter your savings account number (9-18 digits), IFSC code (11 characters: ABCD0123456), and bank name. Account must be in your name or jointly with guardian. Used for direct benefit transfers, scholarships, and refunds.",
        "metadata": {"category": "form_glossary", "field": "bank_account", "tags": ["bank", "ifsc", "direct_transfer"]}
    },
    {
        "id": "form_declaration",
        "text": "Declaration: A legal statement confirming all information provided is true and accurate. By signing/submitting, you declare under penalty of law that details are correct. False declaration can lead to application rejection and legal action. Read carefully before agreeing.",
        "metadata": {"category": "form_glossary", "field": "declaration", "tags": ["legal", "signature", "penalty"]}
    },

    # Accessibility FAQ (10 entries)
    {
        "id": "faq_screen_reader_navigation",
        "text": "Screen Reader Navigation: Use arrow keys to navigate line by line. Press Tab to jump between interactive elements (links, buttons, form fields). Use headings (H1-H6) with screen reader rotor/quick nav to skip sections. Landmarks (main, nav, footer) provide page structure.",
        "metadata": {"category": "accessibility_faq", "topic": "screen_reader_navigation", "tags": ["screen_reader", "keyboard", "headings", "landmarks"]}
    },
    {
        "id": "faq_keyboard_only_forms",
        "text": "Keyboard-Only Form Access: Tab to move between fields. Shift+Tab to go back. Enter/Space to activate buttons and checkboxes. Arrow keys for radio buttons and dropdowns. Escape to close modals/dropdowns. Ensure visible focus indicator at all times.",
        "metadata": {"category": "accessibility_faq", "topic": "keyboard_only_forms", "tags": ["keyboard", "forms", "focus", "tab_order"]}
    },
    {
        "id": "faq_high_contrast_mode",
        "text": "High Contrast Mode: Increases color contrast ratio to at least 4.5:1 for text. Enable in OS settings (Windows: Left Alt+Left Shift+Print Screen; Mac: System Preferences > Accessibility > Display). Helps users with low vision or color blindness read content.",
        "metadata": {"category": "accessibility_faq", "topic": "high_contrast_mode", "tags": ["contrast", "low_vision", "color_blindness", "os_settings"]}
    },
    {
        "id": "faq_alt_text_purpose",
        "text": "Alt Text Purpose: Alternative text describes images for screen reader users. Should be concise (under 125 chars) and convey the image's purpose, not just appearance. Decorative images need empty alt (alt=\"\"). Complex charts need longer descriptions nearby.",
        "metadata": {"category": "accessibility_faq", "topic": "alt_text_purpose", "tags": ["images", "screen_reader", "description", "decorative"]}
    },
    {
        "id": "faq_aria_labels",
        "text": "ARIA Labels: Provide accessible names for elements without visible text (icon buttons, custom controls). Use aria-label for short labels, aria-labelledby to reference existing text. Do not duplicate visible label text. Test with screen reader to verify.",
        "metadata": {"category": "accessibility_faq", "topic": "aria_labels", "tags": ["aria", "labels", "custom_controls", "screen_reader"]}
    },
    {
        "id": "faq_focus_indicators",
        "text": "Focus Indicators: Visible outline showing which element has keyboard focus. Never remove outline (outline: none) without replacement. Minimum 2px solid, 3:1 contrast against background. Essential for keyboard-only users to track position on page.",
        "metadata": {"category": "accessibility_faq", "topic": "focus_indicators", "tags": ["focus", "keyboard", "outline", "visibility"]}
    },
    {
        "id": "faq_form_validation_errors",
        "text": "Form Validation Errors: Announce errors via aria-live (polite) or role=alert. Link error message to field with aria-describedby. Show error inline near field. Preserve user input. Allow easy correction and re-submission. Clear error on valid input.",
        "metadata": {"category": "accessibility_faq", "topic": "form_validation_errors", "tags": ["forms", "validation", "aria_live", "error_handling"]}
    },
    {
        "id": "faq_skip_links",
        "text": "Skip Links: Hidden links at top of page that become visible on focus. Allow jumping to main content, navigation, or search. First focusable element on page. Essential for keyboard users to bypass repetitive headers/menus. Label clearly: 'Skip to main content'.",
        "metadata": {"category": "accessibility_faq", "topic": "skip_links", "tags": ["skip_links", "keyboard", "navigation", "main_content"]}
    },
    {
        "id": "faq_heading_structure",
        "text": "Heading Structure: Use H1 for page title (only one). H2 for major sections. H3-H6 for subsections in order. Never skip levels (H1 to H3). Screen readers use headings for navigation. Proper hierarchy helps all users understand content organization.",
        "metadata": {"category": "accessibility_faq", "topic": "heading_structure", "tags": ["headings", "hierarchy", "screen_reader", "structure"]}
    },
    {
        "id": "faq_landmark_regions",
        "text": "Landmark Regions: HTML5 semantic elements that define page areas: <header>, <nav>, <main>, <aside>, <footer>, <section>. Screen readers list landmarks for quick navigation. Use one <main>. Label duplicate landmarks with aria-label (e.g., 'Primary navigation', 'Footer navigation').",
        "metadata": {"category": "accessibility_faq", "topic": "landmark_regions", "tags": ["landmarks", "html5", "semantic", "screen_reader"]}
    },
]


def initialize_knowledge_base(vector_store) -> int:
    """Initialize the knowledge base with seed documents. Returns count added."""
    existing_count = vector_store.count()
    if existing_count > 0:
        return 0  # Already initialized

    vector_store.add_documents(SEED_DOCUMENTS)
    return len(SEED_DOCUMENTS)