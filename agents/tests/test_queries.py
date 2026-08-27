TEST_QUERIES = {
    "form_agent": [
        {
            "query": "What is the permanent address field asking for?",
            "entity": "Permanent Address field",
            "extra_context": "Form with fields: Name, Date of Birth, Permanent Address, Aadhaar Number",
            "expected_keywords": ["official", "ID proof", "government", "address", "correspondence"]
        },
        {
            "query": "What should I enter in the Aadhaar number field?",
            "entity": "Aadhaar Number field",
            "extra_context": "Government form requiring identity verification",
            "expected_keywords": ["12-digit", "UIDAI", "identity", "verification"]
        },
        {
            "query": "Explain the PAN number format",
            "entity": "PAN Number field",
            "extra_context": "Tax-related form for scholarship application",
            "expected_keywords": ["10-character", "alphanumeric", "Income Tax", "ABCDE1234F"]
        },
        {
            "query": "What date format should I use for date of birth?",
            "entity": "Date of Birth field",
            "extra_context": "Admission form for university",
            "expected_keywords": ["DD/MM/YYYY", "format", "birth certificate"]
        },
        {
            "query": "Whose name goes in the guardian name field?",
            "entity": "Guardian Name field",
            "extra_context": "Student application form",
            "expected_keywords": ["parent", "legal guardian", "father", "mother"]
        },
        {
            "query": "How do I calculate annual income for this form?",
            "entity": "Annual Income field",
            "extra_context": "Scholarship application form",
            "expected_keywords": ["total yearly", "all sources", "salary", "scholarship eligibility"]
        },
        {
            "query": "What caste category options are available?",
            "entity": "Caste Category field",
            "extra_context": "Government job application form",
            "expected_keywords": ["General", "OBC", "SC", "ST", "EWS", "caste certificate"]
        },
        {
            "query": "Where do I find my disability certificate number?",
            "entity": "Disability Certificate field",
            "extra_context": "Form for disability quota benefits",
            "expected_keywords": ["medical board", "government", "certificate number", "state"]
        },
        {
            "query": "What bank details are needed?",
            "entity": "Bank Account field",
            "extra_context": "Scholarship direct transfer form",
            "expected_keywords": ["account number", "IFSC", "bank name", "direct benefit transfer"]
        },
        {
            "query": "What does the declaration mean?",
            "entity": "Declaration field",
            "extra_context": "Final declaration at end of application form",
            "expected_keywords": ["legal statement", "true and accurate", "penalty", "false declaration"]
        },
    ],
    "document_agent": [
        {
            "query": "Summarize this document",
            "entity": "Full document",
            "extra_context": "This is a university admission brochure. It contains information about courses offered (B.Tech, M.Tech, MBA), eligibility criteria (12th pass with 60% for B.Tech), application deadlines (July 31), fee structure (Rs 1,50,000 per year for B.Tech), and contact details.",
            "expected_keywords": ["admission", "B.Tech", "M.Tech", "MBA", "eligibility", "deadline", "fee"]
        },
        {
            "query": "What is the application deadline?",
            "entity": "Deadline",
            "extra_context": "University admission brochure with deadline July 31 for all programs. Late applications accepted with fee until August 15.",
            "expected_keywords": ["July 31", "deadline", "August 15", "late"]
        },
        {
            "query": "What are the eligibility criteria for B.Tech?",
            "entity": "B.Tech Eligibility",
            "extra_context": "B.Tech eligibility: 12th pass with minimum 60% aggregate in Physics, Chemistry, Mathematics. JEE Main score required. Age limit 25 years.",
            "expected_keywords": ["12th pass", "60%", "Physics", "Chemistry", "Mathematics", "JEE Main"]
        },
        {
            "query": "How much is the fee for MBA program?",
            "entity": "MBA Fee",
            "extra_context": "MBA program fee: Rs 2,00,000 per year. Total 2 years. Hostel fee extra Rs 80,000 per year. Scholarships available for merit students.",
            "expected_keywords": ["2,00,000", "per year", "2 years", "hostel", "scholarships"]
        },
        {
            "query": "What documents are required for application?",
            "entity": "Required Documents",
            "extra_context": "Required documents: 10th marksheet, 12th marksheet, JEE scorecard, category certificate (if applicable), passport photo, ID proof, address proof.",
            "expected_keywords": ["10th marksheet", "12th marksheet", "JEE scorecard", "category certificate", "ID proof"]
        },
        {
            "query": "Is there hostel facility mentioned?",
            "entity": "Hostel",
            "extra_context": "Hostel facility available on campus. Separate blocks for boys and girls. Fee: Rs 80,000 per year including mess. Limited seats, allotted on merit basis.",
            "expected_keywords": ["hostel", "campus", "boys", "girls", "80,000", "merit basis"]
        },
        {
            "query": "What is the contact email for admissions?",
            "entity": "Contact Information",
            "extra_context": "For admission queries: email admissions@university.edu, phone 011-23456789. Office hours: Mon-Fri 9AM-5PM. Address: University Campus, Sector 62, Noida.",
            "expected_keywords": ["admissions@university.edu", "011-23456789", "office hours", "Noida"]
        },
        {
            "query": "Are there any scholarships mentioned?",
            "entity": "Scholarships",
            "extra_context": "Merit scholarships: Top 10% get 50% fee waiver. Sports quota: 25% fee waiver. EWS category: 30% fee waiver. Apply separately with income certificate.",
            "expected_keywords": ["merit", "50%", "fee waiver", "sports", "EWS", "income certificate"]
        },
        {
            "query": "What courses are offered in this document?",
            "entity": "Courses Offered",
            "extra_context": "Courses: B.Tech (CSE, ECE, ME, Civil), M.Tech (AI, Data Science, VLSI), MBA (Finance, Marketing, HR), PhD in all departments.",
            "expected_keywords": ["B.Tech", "M.Tech", "MBA", "PhD", "CSE", "ECE", "AI", "Data Science"]
        },
        {
            "query": "Where is the university located?",
            "entity": "Location",
            "extra_context": "University Campus, Sector 62, Noida, Uttar Pradesh 201309. Near Sector 62 Metro Station. 30 mins from Delhi Airport.",
            "expected_keywords": ["Sector 62", "Noida", "Uttar Pradesh", "Metro Station", "Delhi Airport"]
        },
    ],
    "web_agent": [
        {
            "query": "What does the submit button do?",
            "entity": "Submit Button",
            "extra_context": "Form page with personal details, address, and education sections. Submit button at bottom right.",
            "expected_keywords": ["submit", "form", "application", "sends data", "completes"]
        },
        {
            "query": "How do I navigate the main menu?",
            "entity": "Main Navigation Menu",
            "extra_context": "Website header with logo, navigation links: Home, Courses, Admissions, About Us, Contact. Dropdown under Courses.",
            "expected_keywords": ["Tab", "arrow keys", "Enter", "dropdown", "Home", "Courses", "Admissions"]
        },
        {
            "query": "What is this checkbox for?",
            "entity": "Terms Checkbox",
            "extra_context": "Registration form with checkbox labeled 'I agree to Terms and Conditions' next to submit button.",
            "expected_keywords": ["agree", "Terms and Conditions", "required", "checkbox", "Space", "Enter"]
        },
        {
            "query": "How do I use the date picker?",
            "entity": "Date Picker",
            "extra_context": "Date of birth field with calendar icon. Clicking opens date picker widget.",
            "expected_keywords": ["calendar", "date picker", "arrow keys", "Enter", "Tab", "format"]
        },
        {
            "query": "What does the search box do?",
            "entity": "Search Box",
            "extra_context": "Header search box with placeholder 'Search courses...' and magnifying glass icon.",
            "expected_keywords": ["search", "courses", "type", "Enter", "results", "filter"]
        },
        {
            "query": "Explain the dropdown for course selection",
            "entity": "Course Dropdown",
            "extra_context": "Application form with dropdown labeled 'Select Course' showing B.Tech, M.Tech, MBA options.",
            "expected_keywords": ["dropdown", "arrow keys", "Enter", "options", "B.Tech", "M.Tech", "MBA"]
        },
        {
            "query": "What happens when I click the login link?",
            "entity": "Login Link",
            "extra_context": "Top right corner has 'Login' link. User is not logged in.",
            "expected_keywords": ["login", "redirect", "credentials", "dashboard", "account"]
        },
        {
            "query": "How do I fill the address autocomplete?",
            "entity": "Address Autocomplete",
            "extra_context": "Address field with autocomplete suggestions as you type. Powered by Google Places.",
            "expected_keywords": ["autocomplete", "type", "suggestions", "arrow keys", "select", "Google Places"]
        },
        {
            "query": "What is the purpose of the captcha?",
            "entity": "Captcha",
            "extra_context": "Form has 'I am not a robot' checkbox captcha before submit button.",
            "expected_keywords": ["robot", "verify", "human", "automated", "security", "checkbox"]
        },
        {
            "query": "How do I access the help section?",
            "entity": "Help Link",
            "extra_context": "Footer has 'Help' link alongside Privacy Policy, Terms of Service, Contact Us.",
            "expected_keywords": ["Help", "footer", "link", "support", "FAQ", "contact"]
        },
    ],
    "education_agent": [
        {
            "query": "Explain photosynthesis in simple terms",
            "entity": "Photosynthesis",
            "extra_context": "High school biology student asking for explanation",
            "expected_keywords": ["plants", "sunlight", "carbon dioxide", "oxygen", "glucose", "energy"]
        },
        {
            "query": "What is Newton's first law of motion?",
            "entity": "Newton's First Law",
            "extra_context": "Physics student learning about laws of motion",
            "expected_keywords": ["inertia", "rest", "motion", "external force", "object", "continues"]
        },
        {
            "query": "Simplify quantum mechanics for me",
            "entity": "Quantum Mechanics",
            "extra_context": "College student struggling with quantum physics concepts",
            "expected_keywords": ["particles", "waves", "probability", "uncertainty", "observation", "simplified"]
        },
        {
            "query": "How does photosynthesis work step by step?",
            "entity": "Photosynthesis Process",
            "extra_context": "Student needs detailed but simple breakdown of photosynthesis stages",
            "expected_keywords": ["light-dependent", "Calvin cycle", "chlorophyll", "water", "oxygen", "glucose"]
        },
        {
            "query": "Give me an example of Newton's third law",
            "entity": "Newton's Third Law Example",
            "extra_context": "Student wants real-world example of action-reaction principle",
            "expected_keywords": ["action", "reaction", "equal", "opposite", "rocket", "swimming", "walking"]
        },
        {
            "query": "What is the difference between mitosis and meiosis?",
            "entity": "Mitosis vs Meiosis",
            "extra_context": "Biology student confused between cell division types",
            "expected_keywords": ["mitosis", "meiosis", "identical", "gametes", "chromosomes", "division"]
        },
        {
            "query": "Explain gravity simply",
            "entity": "Gravity",
            "extra_context": "Middle school student asking about gravitational force",
            "expected_keywords": ["force", "attracts", "mass", "Earth", "fall", "Newton", "apple"]
        },
        {
            "query": "How do vaccines work?",
            "entity": "Vaccines",
            "extra_context": "Health education context - explaining immunization",
            "expected_keywords": ["immune system", "antibodies", "pathogen", "memory", "protection", "weakened"]
        },
        {
            "query": "What is climate change?",
            "entity": "Climate Change",
            "extra_context": "Environmental science student seeking clear explanation",
            "expected_keywords": ["temperature", "greenhouse gases", "carbon dioxide", "global warming", "human activity"]
        },
        {
            "query": "Explain how a battery works",
            "entity": "Battery",
            "extra_context": "Physics/chemistry student learning about electrochemistry",
            "expected_keywords": ["chemical energy", "electrical energy", "electrons", "anode", "cathode", "circuit"]
        },
    ],
    "general_agent": [
        {
            "query": "Hello, how can you help me?",
            "entity": "General Greeting",
            "extra_context": "",
            "expected_keywords": ["help", "assist", "question", "accessibility"]
        },
        {
            "query": "What can you do?",
            "entity": "Capabilities",
            "extra_context": "",
            "expected_keywords": ["form", "document", "web", "education", "explain", "navigate"]
        },
    ],
}