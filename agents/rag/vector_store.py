import faiss
import numpy as np
import json
import os
from pathlib import Path
from config import settings
from .embeddings import EmbeddingModel
import uuid


class VectorStore:
    _instance = None
    _index = None
    _documents = None
    _id_to_idx = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._index is None:
            self.persist_dir = Path(settings.CHROMA_PERSIST_DIR)
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            
            self.index_path = self.persist_dir / "faiss.index"
            self.docs_path = self.persist_dir / "documents.json"
            self.mapping_path = self.persist_dir / "id_mapping.json"
            
            self._embedding_model = EmbeddingModel()
            self._load_or_create()

    def _load_or_create(self):
        if self.index_path.exists() and self.docs_path.exists():
            self._index = faiss.read_index(str(self.index_path))
            with open(self.docs_path, 'r') as f:
                self._documents = json.load(f)
            with open(self.mapping_path, 'r') as f:
                self._id_to_idx = json.load(f)
        else:
            # Get embedding dimension
            test_emb = self._embedding_model.encode_single("test")
            dim = test_emb.shape[0]
            
            self._index = faiss.IndexFlatIP(dim)  # Inner product for cosine similarity
            self._documents = []
            self._id_to_idx = {}
            self._save()

    def _save(self):
        faiss.write_index(self._index, str(self.index_path))
        with open(self.docs_path, 'w') as f:
            json.dump(self._documents, f)
        with open(self.mapping_path, 'w') as f:
            json.dump(self._id_to_idx, f)

    def add_documents(self, documents: list[dict]) -> None:
        if not documents:
            return

        texts = [doc["text"] for doc in documents]
        embeddings = self._embedding_model.encode(texts).astype('float32')
        
        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings)
        
        start_idx = len(self._documents)
        for i, doc in enumerate(documents):
            doc_id = doc.get("id", str(uuid.uuid4()))
            self._id_to_idx[doc_id] = start_idx + i
            self._documents.append({
                "id": doc_id,
                "text": doc["text"],
                "metadata": doc.get("metadata", {})
            })
        
        self._index.add(embeddings)
        self._save()

    def query(self, query_text: str, k: int = None) -> list[dict]:
        if k is None:
            k = settings.TOP_K
        
        if self._index.ntotal == 0:
            return []
        
        query_embedding = self._embedding_model.encode_single(query_text).astype('float32').reshape(1, -1)
        faiss.normalize_L2(query_embedding)
        
        scores, indices = self._index.search(query_embedding, min(k, self._index.ntotal))
        
        docs = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self._documents):
                doc = self._documents[idx].copy()
                doc["distance"] = float(1.0 - score)  # Convert similarity to distance
                docs.append(doc)
        return docs

    def count(self) -> int:
        return self._index.ntotal if self._index else 0

    def reset(self) -> None:
        if self.index_path.exists():
            self.index_path.unlink()
        if self.docs_path.exists():
            self.docs_path.unlink()
        if self.mapping_path.exists():
            self.mapping_path.unlink()
        self._load_or_create()