"""Quick integration test for the full pipeline with mocks"""
import asyncio
import httpx
import json


async def test_mock_intent():
    async with httpx.AsyncClient(base_url="http://localhost:8001", timeout=10.0) as client:
        # Test form_help
        resp = await client.post("/intent/classify", json={
            "session_id": "test-123",
            "input_text": "What is this field asking for?",
            "screen_context": "form with fields: Name, DOB, Permanent Address",
            "history": []
        })
        print("Intent (form):", resp.json())
        
        # Test document_help
        resp = await client.post("/intent/classify", json={
            "session_id": "test-123",
            "input_text": "Summarize this PDF for me",
            "screen_context": "PDF document open",
            "history": []
        })
        print("Intent (doc):", resp.json())
        
        # Test web_navigation_help
        resp = await client.post("/intent/classify", json={
            "session_id": "test-123",
            "input_text": "How do I navigate to the scholarships page?",
            "screen_context": "university website homepage",
            "history": []
        })
        print("Intent (web):", resp.json())
        
        # Test education_help
        resp = await client.post("/intent/classify", json={
            "session_id": "test-123",
            "input_text": "Explain photosynthesis in simple terms",
            "screen_context": "biology textbook page",
            "history": []
        })
        print("Intent (edu):", resp.json())


async def test_mock_agent():
    async with httpx.AsyncClient(base_url="http://localhost:8002", timeout=10.0) as client:
        # Test form_agent
        resp = await client.post("/agent/respond", json={
            "session_id": "test-123",
            "agent": "form_agent",
            "query": "What is this field asking for?",
            "entity": "Permanent Address field",
            "extra_context": "form with fields: Name, DOB, Permanent Address"
        })
        print("Agent (form):", resp.json())
        
        # Test document_agent
        resp = await client.post("/agent/respond", json={
            "session_id": "test-123",
            "agent": "document_agent",
            "query": "Summarize this document",
            "entity": "document content",
            "extra_context": "PDF rental agreement"
        })
        print("Agent (doc):", resp.json())
        
        # Test web_agent
        resp = await client.post("/agent/respond", json={
            "session_id": "test-123",
            "agent": "web_agent",
            "query": "How to submit this form?",
            "entity": "submit button",
            "extra_context": "application form page"
        })
        print("Agent (web):", resp.json())
        
        # Test education_agent
        resp = await client.post("/agent/respond", json={
            "session_id": "test-123",
            "agent": "education_agent",
            "query": "What is photosynthesis?",
            "entity": "photosynthesis",
            "extra_context": "biology chapter"
        })
        print("Agent (edu):", resp.json())


async def test_backend():
    """Test full backend pipeline (requires running backend on 8000)"""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as client:
        # Register
        resp = await client.post("/auth/register", json={
            "email": "test@example.com",
            "password": "testpass123"
        })
        print("Register:", resp.json())
        token = resp.json()["access_token"]
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create session
        resp = await client.post("/api/session", headers=headers)
        print("Create session:", resp.json())
        session_id = resp.json()["session_id"]
        
        # Query
        resp = await client.post("/api/query", headers=headers, json={
            "session_id": session_id,
            "input_text": "What is this field asking for?",
            "input_source": "text",
            "screen_context": "form with fields: Name, DOB, Permanent Address"
        })
        print("Query:", resp.json())
        
        # History
        resp = await client.get(f"/api/history/{session_id}", headers=headers)
        print("History:", resp.json())


if __name__ == "__main__":
    print("=== Testing Mock Intent Service (port 8001) ===")
    asyncio.run(test_mock_intent())
    
    print("\n=== Testing Mock Agent Service (port 8002) ===")
    asyncio.run(test_mock_agent())
    
    # Uncomment to test full backend (requires backend running on 8000)
    # print("\n=== Testing Backend (port 8000) ===")
    # asyncio.run(test_backend())