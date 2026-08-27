"""
Mock Task Agents + RAG Service
Runs on port 8002
Returns realistic agent responses for demo/development
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Mock Agent Service")


class AgentRequest(BaseModel):
    session_id: str
    agent: str
    query: str
    entity: str
    extra_context: str = ""


class AgentResponse(BaseModel):
    answer: str
    sources_used: list[str]
    suggested_action: Optional[str] = None


# Mock responses per agent type
MOCK_RESPONSES = {
    "form_agent": {
        "default": {
            "answer": "This field is asking for your permanent address as listed on your government ID proof (like Aadhaar, passport, or driver's license), not your current residence address.",
            "sources_used": ["form-field-glossary.md#permanent-address"],
            "suggested_action": "highlight_field"
        },
        "aadhar": {
            "answer": "The Aadhaar number field requires your 12-digit unique identification number issued by UIDAI. Enter it without spaces or dashes.",
            "sources_used": ["form-field-glossary.md#aadhar-number"],
            "suggested_action": "highlight_field"
        },
        "dob": {
            "answer": "Date of Birth should be entered in DD/MM/YYYY format as per your birth certificate or official ID document.",
            "sources_used": ["form-field-glossary.md#date-of-birth"],
            "suggested_action": "highlight_field"
        },
    },
    "document_agent": {
        "default": {
            "answer": "Based on the document you uploaded, this section covers the terms and conditions for service usage. Key points: 1) You agree to the privacy policy, 2) Data may be shared with third parties, 3) You can terminate anytime with 30 days notice.",
            "sources_used": ["uploaded-document.pdf#section-4"],
            "suggested_action": "scroll_to_section"
        },
        "summary": {
            "answer": "This document is a rental agreement for a 2BHK apartment in Bangalore. Monthly rent: Rs. 25,000. Security deposit: Rs. 50,000. Lease term: 11 months. Key clauses: maintenance charges, notice period, pet policy.",
            "sources_used": ["uploaded-document.pdf#all"],
            "suggested_action": "none"
        },
    },
    "web_agent": {
        "default": {
            "answer": "The 'Submit Application' button at the bottom of the form will send your completed application to the university admissions office. Make sure all required fields (marked with *) are filled before clicking.",
            "sources_used": ["web-accessibility-guide.md#form-submission"],
            "suggested_action": "highlight_button"
        },
        "navigation": {
            "answer": "To reach the 'Scholarships' section: 1) Click the menu icon (☰) in top-right, 2) Select 'Student Services', 3) Choose 'Scholarships & Financial Aid' from the dropdown.",
            "sources_used": ["web-accessibility-guide.md#navigation-menu"],
            "suggested_action": "none"
        },
    },
    "education_agent": {
        "default": {
            "answer": "Photosynthesis is the process by which green plants convert sunlight, water, and carbon dioxide into glucose (food) and oxygen. Think of it as plants making their own food using solar energy.",
            "sources_used": ["biology-basics.md#photosynthesis"],
            "suggested_action": "none"
        },
        "concept": {
            "answer": "Machine learning is a subset of AI where computers learn patterns from data without being explicitly programmed. Instead of writing rules, you show examples and the system figures out the rules.",
            "sources_used": ["ml-intro.md#what-is-ml"],
            "suggested_action": "none"
        },
    },
    "general_agent": {
        "default": {
            "answer": "I'm here to help you with forms, documents, websites, and learning. Could you clarify what you'd like assistance with?",
            "sources_used": ["general-faq.md#welcome"],
            "suggested_action": "none"
        },
    }
}


def get_mock_response(agent: str, query: str, entity: str) -> dict:
    """Get appropriate mock response based on agent and query keywords."""
    agent_responses = MOCK_RESPONSES.get(agent, MOCK_RESPONSES["general_agent"])
    query_lower = query.lower()
    entity_lower = entity.lower()
    
    # Try to match specific keywords
    if agent == "form_agent":
        if "aadhar" in query_lower or "aadhar" in entity_lower:
            return agent_responses["aadhar"]
        if "dob" in query_lower or "birth" in query_lower or "date" in entity_lower:
            return agent_responses["dob"]
    
    if agent == "document_agent":
        if "summarize" in query_lower or "summary" in query_lower:
            return agent_responses["summary"]
    
    if agent == "web_agent":
        if "navigate" in query_lower or "find" in query_lower or "where" in query_lower:
            return agent_responses["navigation"]
    
    if agent == "education_agent":
        if "photosynthesis" in query_lower:
            return agent_responses["default"]
        if "machine learning" in query_lower or "ml" in query_lower:
            return agent_responses["concept"]
    
    return agent_responses["default"]


@app.post("/agent/respond", response_model=AgentResponse)
async def agent_respond(request: AgentRequest):
    response_data = get_mock_response(request.agent, request.query, request.entity)
    return AgentResponse(**response_data)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-agent"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)