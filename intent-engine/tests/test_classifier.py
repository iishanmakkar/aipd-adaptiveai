"""Test cases for intent classifier - 20+ examples covering all 5 categories"""

TEST_CASES = [
    # form_help (4 cases)
    ("What is this field asking for?", "form_help", "form_agent"),
    ("How do I fill the permanent address field?", "form_help", "form_agent"),
    ("What does the Aadhaar number field mean?", "form_help", "form_agent"),
    ("Help me fill this application form", "form_help", "form_agent"),
    
    # document_help (4 cases)
    ("Summarize this PDF for me", "document_help", "document_agent"),
    ("What does this contract clause mean?", "document_help", "document_agent"),
    ("Extract key points from this document", "document_help", "document_agent"),
    ("Read the terms and conditions to me", "document_help", "document_agent"),
    
    # web_navigation_help (4 cases)
    ("How do I navigate to the scholarships page?", "web_navigation_help", "web_agent"),
    ("Where is the submit button on this page?", "web_navigation_help", "web_agent"),
    ("Help me find the login link", "web_navigation_help", "web_agent"),
    ("What does this menu item do?", "web_navigation_help", "web_agent"),
    
    # education_help (4 cases)
    ("Explain photosynthesis in simple terms", "education_help", "education_agent"),
    ("What is machine learning?", "education_help", "education_agent"),
    ("Teach me about the water cycle", "education_help", "education_agent"),
    ("Define Newton's laws of motion", "education_help", "education_agent"),
    
    # general_query (4 cases)
    ("Hello, how are you?", "general_query", "general_agent"),
    ("What can you help me with?", "general_query", "general_agent"),
    ("Thanks for your help", "general_query", "general_agent"),
    ("Goodbye", "general_query", "general_agent"),
]

# Additional edge cases with context
CONTEXT_TEST_CASES = [
    # With screen context hinting at form
    ("What about this one?", "form_help", "form_agent", "form with fields: Name, Email, Phone"),
    ("And this field?", "form_help", "form_agent", "form with fields: Address, City, Zip"),
    
    # With screen context hinting at document
    ("Summarize it", "document_help", "document_agent", "PDF document open: rental agreement"),
    ("What does section 4 say?", "document_help", "document_agent", "document showing terms of service"),
    
    # With screen context hinting at web
    ("Click it", "web_navigation_help", "web_agent", "webpage with Submit Application button"),
    ("Go there", "web_navigation_help", "web_agent", "website navigation menu visible"),
    
    # With screen context hinting at education
    ("Explain this concept", "education_help", "education_agent", "textbook page about photosynthesis"),
    ("What is this?", "education_help", "education_agent", "educational content about DNA"),
]


def run_accuracy_test():
    """Run classifier against test cases and report accuracy."""
    import asyncio
    import httpx
    
    async def test():
        correct = 0
        total = 0
        results = []
        
        # Test without context first
        for text, expected_intent, expected_agent in TEST_CASES:
            async with httpx.AsyncClient(base_url="http://localhost:8001", timeout=30.0) as client:
                resp = await client.post("/intent/classify", json={
                    "session_id": f"test-{total}",
                    "input_text": text,
                    "screen_context": "",
                    "history": []
                })
                result = resp.json()
                predicted_intent = result["intent"]
                predicted_agent = result["target_agent"]
                
                is_correct = (predicted_intent == expected_intent and predicted_agent == expected_agent)
                if is_correct:
                    correct += 1
                total += 1
                
                results.append({
                    "input": text,
                    "expected": f"{expected_intent}/{expected_agent}",
                    "predicted": f"{predicted_intent}/{predicted_agent}",
                    "correct": is_correct,
                    "reasoning": result.get("reasoning", "")
                })
                print(f"{'✓' if is_correct else '✗'} '{text[:50]}...' -> {predicted_intent}/{predicted_agent} (expected: {expected_intent}/{expected_agent})")
        
        # Test with context
        for text, expected_intent, expected_agent, context in CONTEXT_TEST_CASES:
            async with httpx.AsyncClient(base_url="http://localhost:8001", timeout=30.0) as client:
                resp = await client.post("/intent/classify", json={
                    "session_id": f"test-ctx-{total}",
                    "input_text": text,
                    "screen_context": context,
                    "history": []
                })
                result = resp.json()
                predicted_intent = result["intent"]
                predicted_agent = result["target_agent"]
                
                is_correct = (predicted_intent == expected_intent and predicted_agent == expected_agent)
                if is_correct:
                    correct += 1
                total += 1
                
                results.append({
                    "input": text,
                    "context": context,
                    "expected": f"{expected_intent}/{expected_agent}",
                    "predicted": f"{predicted_intent}/{predicted_agent}",
                    "correct": is_correct,
                    "reasoning": result.get("reasoning", "")
                })
                print(f"{'✓' if is_correct else '✗'} '{text}' [ctx] -> {predicted_intent}/{predicted_agent} (expected: {expected_intent}/{expected_agent})")
        
        accuracy = correct / total * 100
        print(f"\n{'='*50}")
        print(f"Accuracy: {correct}/{total} = {accuracy:.1f}%")
        print(f"{'='*50}")
        
        return results, accuracy
    
    return asyncio.run(test())


if __name__ == "__main__":
    run_accuracy_test()