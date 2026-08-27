import asyncio
import json
import sys
from datetime import datetime
from typing import Dict, List
from config import settings
from rag.vector_store import VectorStore
from rag.seed_data import initialize_knowledge_base
from rag.retriever import Retriever
from llm.client import LLMClient
from agents.registry import AgentRegistry
from tests.test_queries import TEST_QUERIES


async def run_tests():
    print("=" * 60)
    print("AdaptiveAI Task Agents - Test Suite")
    print("=" * 60)
    
    # Initialize components
    vector_store = VectorStore()
    initialize_knowledge_base(vector_store)
    retriever = Retriever()
    llm_client = LLMClient()
    agent_registry = AgentRegistry(retriever, llm_client)
    
    print(f"\nKnowledge base: {vector_store.count()} documents")
    print(f"LLM Provider: {settings.LLM_PROVIDER} ({settings.LLM_MODEL})")
    print(f"Test timestamp: {datetime.now().isoformat()}")
    
    results = {}
    total_tests = 0
    passed_tests = 0
    
    for agent_name, queries in TEST_QUERIES.items():
        agent = agent_registry.get(agent_name)
        if not agent:
            print(f"\n⚠️  Agent '{agent_name}' not found, skipping...")
            continue
        
        print(f"\n--- Testing {agent_name} ---")
        agent_results = []
        
        for i, test_case in enumerate(queries, 1):
            total_tests += 1
            query = test_case["query"]
            entity = test_case["entity"]
            extra_context = test_case.get("extra_context", "")
            expected_keywords = test_case.get("expected_keywords", [])
            
            print(f"  Test {i}: {query[:60]}...")
            
            try:
                result = await agent.handle(query, entity, extra_context)
                answer = result["answer"].lower()
                sources = result["sources_used"]
                action = result["suggested_action"]
                
                # Check expected keywords
                found_keywords = [kw for kw in expected_keywords if kw.lower() in answer]
                missing_keywords = [kw for kw in expected_keywords if kw.lower() not in answer]
                
                passed = len(missing_keywords) == 0
                if passed:
                    passed_tests += 1
                    status = "✅ PASS"
                else:
                    status = "❌ FAIL"
                
                test_result = {
                    "query": query,
                    "entity": entity,
                    "answer": result["answer"],
                    "sources_used": sources,
                    "suggested_action": action,
                    "expected_keywords": expected_keywords,
                    "found_keywords": found_keywords,
                    "missing_keywords": missing_keywords,
                    "passed": passed
                }
                agent_results.append(test_result)
                
                print(f"    {status} - Keywords: {len(found_keywords)}/{len(expected_keywords)} found")
                if missing_keywords:
                    print(f"    Missing: {missing_keywords}")
                
            except Exception as e:
                print(f"    ❌ ERROR: {str(e)}")
                agent_results.append({
                    "query": query,
                    "error": str(e),
                    "passed": False
                })
        
        results[agent_name] = agent_results
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Pass rate: {passed_tests/total_tests*100:.1f}%" if total_tests > 0 else "N/A")
    
    # Per-agent summary
    for agent_name, agent_results in results.items():
        agent_passed = sum(1 for r in agent_results if r.get("passed", False))
        agent_total = len(agent_results)
        print(f"  {agent_name}: {agent_passed}/{agent_total} ({agent_passed/agent_total*100:.1f}%)" if agent_total > 0 else f"  {agent_name}: N/A")
    
    # Save detailed results
    output_file = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "llm_provider": settings.LLM_PROVIDER,
            "llm_model": settings.LLM_MODEL,
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "results": results
        }, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_file}")
    
    return passed_tests == total_tests


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)