class MockLLMClient:
    """Mock LLM client for testing - returns responses with expected keywords based on full prompt."""
    
    def __init__(self):
        self.provider = "mock"
        self.model = "mock-model"
    
    def chat(self, messages: list[dict]) -> str:
        # Get the user message which contains the full prompt with context
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "").lower()
        
        # Form agent responses with expected keywords
        if "permanent address" in user_msg:
            return "Permanent Address is your official residential address as listed on government-issued ID proof (Aadhaar, Voter ID, Passport). It is NOT your current temporary address or hostel address. Used for official correspondence and verification."
        elif "aadhaar" in user_msg or "aadhar" in user_msg:
            return "Aadhaar Number is a 12-digit unique identification number issued by UIDAI. Enter all 12 digits without spaces or dashes. This is used for identity verification and linking government services."
        elif "pan" in user_msg:
            return "PAN Number is a 10-character alphanumeric code (format: ABCDE1234F) issued by Income Tax Department. First 5 characters are letters, next 4 are numbers, last is a letter. Required for financial transactions and tax filing."
        elif "date of birth" in user_msg:
            return "Date of Birth should be entered in DD/MM/YYYY format (day/month/year). Example: 15/08/1995. This must match your birth certificate and other official documents."
        elif "guardian" in user_msg:
            return "Guardian Name is the full legal name of your parent or legal guardian. If father is guardian, enter father's full name. If mother, enter mother's name."
        elif "annual income" in user_msg:
            return "Annual Income is your total yearly income from all sources (salary, business, investments, etc.) in Indian Rupees. Used for scholarship eligibility and fee concessions."
        elif "caste" in user_msg:
            return "Caste Category: Select General, OBC (Other Backward Classes), SC (Scheduled Caste), ST (Scheduled Tribe), or EWS (Economically Weaker Section) as per your caste certificate. Determines reservation benefits."
        elif "disability" in user_msg:
            return "Disability Certificate Number is from your disability certificate issued by a government medical board. Enter the certificate number exactly as shown. Used for disability quota and concessions."
        elif "bank" in user_msg and ("account" in user_msg or "detail" in user_msg):
            return "Bank Account Details: Enter your savings account number (9-18 digits), IFSC code (11 characters: ABCD0123456), and bank name. Account must be in your name. Used for direct benefit transfers and refunds."
        elif "declaration" in user_msg:
            return "Declaration is a legal statement confirming all information provided is true and accurate. By signing, you declare under penalty of law that details are correct. False declaration can lead to rejection and legal action."
        
        # Document agent responses
        elif "summarize" in user_msg and "document" in user_msg:
            return "This university admission brochure contains information about courses offered (B.Tech, M.Tech, MBA), eligibility criteria (12th pass with 60% for B.Tech), application deadlines (July 31), fee structure (Rs 1,50,000 per year for B.Tech), and contact details."
        elif "deadline" in user_msg:
            return "The application deadline is July 31 for all programs. Late applications accepted with fee until August 15."
        elif "eligibility" in user_msg and "b.tech" in user_msg:
            return "B.Tech eligibility: 12th pass with minimum 60% aggregate in Physics, Chemistry, Mathematics. JEE Main score required. Age limit 25 years."
        elif "fee" in user_msg and "mba" in user_msg:
            return "MBA program fee: Rs 2,00,000 per year. Total 2 years. Hostel fee extra Rs 80,000 per year. Scholarships available for merit students."
        elif "document" in user_msg and "required" in user_msg:
            return "Required documents: 10th marksheet, 12th marksheet, JEE scorecard, category certificate (if applicable), passport photo, ID proof, address proof."
        elif "hostel" in user_msg:
            return "Hostel facility available on campus. Separate blocks for boys and girls. Fee: Rs 80,000 per year including mess. Limited seats, allotted on merit basis."
        elif "contact" in user_msg or "email" in user_msg:
            return "For admission queries: email admissions@university.edu, phone 011-23456789. Office hours: Mon-Fri 9AM-5PM. Address: University Campus, Sector 62, Noida."
        elif "scholarship" in user_msg:
            return "Merit scholarships: Top 10% get 50% fee waiver. Sports quota: 25% fee waiver. EWS category: 30% fee waiver. Apply separately with income certificate."
        elif "course" in user_msg and "offer" in user_msg:
            return "Courses: B.Tech (CSE, ECE, ME, Civil), M.Tech (AI, Data Science, VLSI), MBA (Finance, Marketing, HR), PhD in all departments."
        elif "location" in user_msg or "where" in user_msg:
            return "University Campus, Sector 62, Noida, Uttar Pradesh 201309. Near Sector 62 Metro Station. 30 mins from Delhi Airport."
        
        # Web agent responses
        elif "submit" in user_msg and "button" in user_msg:
            return "The Submit button sends your form data to the server for processing and completes your application submission."
        elif "menu" in user_msg or "navigation" in user_msg:
            return "Use Tab to navigate menu items (Home, Courses, Admissions, About Us, Contact), Enter to activate, arrow keys for dropdowns under Courses."
        elif "checkbox" in user_msg:
            return "The checkbox confirms you agree to Terms and Conditions. Press Space or Enter to toggle. Required before submitting."
        elif "date picker" in user_msg:
            return "Click the calendar icon to open date picker. Use arrow keys to navigate, Enter to select date. Tab to move between fields."
        elif "search" in user_msg:
            return "Type in the search box to search courses. Press Enter to see results. Filters available for course type, level."
        elif "dropdown" in user_msg:
            return "Use arrow keys to navigate dropdown options (B.Tech, M.Tech, MBA), press Enter to select your course."
        elif "login" in user_msg:
            return "The Login link redirects to authentication page. Enter credentials to access your dashboard and account."
        elif "autocomplete" in user_msg:
            return "Type in the address field; Google Places autocomplete suggestions appear. Use arrow keys to select, Enter to confirm."
        elif "captcha" in user_msg:
            return "The captcha verifies you are human, not a robot. Click the checkbox or solve the automated challenge for security."
        elif "help" in user_msg and ("section" in user_msg or "access" in user_msg or "footer" in user_msg):
            return "The Help link in the footer provides support resources, FAQs, and contact information for assistance."
        
        # Education agent responses
        elif "photosynthesis" in user_msg and "simple" in user_msg:
            return "Photosynthesis is how plants make food using sunlight, carbon dioxide, and water to produce oxygen and glucose for energy."
        elif "newton" in user_msg and "first" in user_msg:
            return "Newton's First Law (inertia): An object at rest stays at rest, and an object in motion continues in motion unless acted upon by an external force."
        elif "quantum" in user_msg:
            return "Quantum mechanics studies particles at the smallest scales where they behave like both particles and waves. Key concepts: probability, uncertainty principle, observation affects outcome."
        elif "photosynthesis" in user_msg and "step" in user_msg:
            return "Photosynthesis steps: 1) Light-dependent reactions (chlorophyll captures sunlight), 2) Calvin cycle (carbon dioxide fixed into glucose). Oxygen released as byproduct."
        elif "newton" in user_msg and "third" in user_msg:
            return "Newton's Third Law: For every action there is an equal and opposite reaction. Examples: rocket launch, swimming, walking."
        elif "mitosis" in user_msg and "meiosis" in user_msg:
            return "Mitosis produces two identical daughter cells for growth. Meiosis produces four genetically different gametes (sperm/egg) with half the chromosomes."
        elif "gravity" in user_msg:
            return "Gravity is a force that attracts objects with mass toward each other. Earth's gravity pulls things down (like Newton's apple). Keeps us on the ground."
        elif "vaccine" in user_msg:
            return "Vaccines train your immune system to recognize and fight pathogens by creating antibodies and memory cells for future protection. Uses weakened or inactive pathogens."
        elif "climate" in user_msg:
            return "Climate change is long-term shifts in temperature and weather patterns, mainly caused by human activities (greenhouse gases, carbon dioxide) leading to global warming."
        elif "battery" in user_msg:
            return "A battery converts chemical energy into electrical energy. Electrons flow from anode to cathode through a circuit, creating current."
        
        # General agent
        elif "hello" in user_msg or "help" in user_msg:
            return "Hello! I can help you with forms, documents, web navigation, and educational topics. Ask me any question about accessibility."
        elif "what can you do" in user_msg:
            return "I can explain form fields, answer document questions, guide web navigation, and simplify educational concepts. I assist with accessibility needs."
        else:
            return "I can help explain that. Please provide more details about what you'd like to know."