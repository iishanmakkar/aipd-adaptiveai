from .vector_store import VectorStore
from config import settings
from typing import List, Dict


class Retriever:
    def __init__(self):
        self.vector_store = VectorStore()
        self.top_k = settings.TOP_K

    def retrieve(self, query: str, k: int = None) -> List[Dict]:
        """Retrieve top-k relevant documents for a query."""
        if k is None:
            k = self.top_k
        return self.vector_store.query(query, k=k)

    def format_sources(self, docs: List[Dict]) -> str:
        """Format retrieved documents for prompt inclusion."""
        if not docs:
            return "No relevant documents found."
        
        lines = []
        for i, doc in enumerate(docs, 1):
            metadata = doc.get("metadata", {})
            source_id = doc.get("id", f"doc_{i}")
            category = metadata.get("category", "unknown")
            field_or_topic = metadata.get("field") or metadata.get("topic", "general")
            lines.append(f"[{i}] [{category}:{field_or_topic}] {doc['text'][:300]}...")
        
        return "\n".join(lines)

    def get_source_ids(self, docs: List[Dict]) -> List[str]:
        """Extract source IDs from retrieved documents."""
        return [doc.get("id", "") for doc in docs if doc.get("id")]