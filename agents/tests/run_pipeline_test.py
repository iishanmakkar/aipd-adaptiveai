import asyncio
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from rag.vector_store import VectorStore
from rag.seed_data import initialize_knowledge_base
from rag.retriever import Retriever
from llm.mock_client import MockLLMClient
from agents.registry import AgentRegistry


async def run_pipeline_test():
    print("=" * 60)
    print("AdaptiveAI Task Agents - Pipeline Validation")
    print("=" * 60)
    
    # Initialize components
    vector_store = VectorStore()
    initialize_knowledge_base(vector_store)
    retriever = Retriever()
    llm_client = MockLLMClient()
    agent_registry = AgentRegistry(retriever, llm_client)
    
    print(f"\nKnowledge base: {vector_store.count()} documents")
    print(f"Available agents: {agent_registry.get_all_names()}")
    
    # Test each agent with a simple query
    test_cases = [
        ("form_agent", "What is permanent address?", "Permanent Address field", "Form with fields"),
        ("document_agent", "Summarize this document", "Full document", "University brochure with B.Tech, MBA courses, deadline July 31"),
        ("web_agent", "What does submit button do?", "Submit Button", "Form page with submit button"),
        ("education_agent", "Explain photosynthesis", "Photosynthesis", "High school biology"),
        ("general_agent", "Hello", "General", ""),
    ]
    
    print("\n--- Pipeline Tests ---")
    all_passed = True
    
    for agent_name, query, entity, context in test_cases:
        agent = agent_registry.get(agent_name)
        if not agent:
            print(f"  {agent_name}: NOT FOUND")
            all_passed = False
            continue
        
        try:
            result = await agent.handle(query, entity, context)
            answer = result["answer"]
            sources = result["sources_used"]
            action = result["suggested_action"]
            
            # Basic validation: answer should be non-empty string
            if answer and len(answer) > 10:
                print(f"  {agent_name}: OK - {len(answer)} chars, {len(sources)} sources, action={action}")
            else:
                print(f"  {agent_name}: FAIL - empty or too short answer")
                all_passed = False
        except Exception as e:
            print(f"  {agent_name}: ERROR - {e}")
            all_passed = False
    
    # Test retrieval
    print("\n--- Retrieval Tests ---")
    queries = [
        "What is permanent address?",
        "Aadhaar number format",
        "photosynthesis process",
        "Newton's first law",
        "screen reader navigation",
    ]
    
    for q in queries:
        docs = retriever.retrieve(q, k=3)
        if docs:
            print(f"  '{q[:30]}...': {len(docs)} docs retrieved (top: {docs[0]['id']})")
        else:
            print(f"  '{q[:30]}...': NO RESULTS")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL PIPELINE TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_pipeline_test())
    sys.exit(0 if success else 1)