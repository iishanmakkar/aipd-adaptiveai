"""Pytest bootstrap + shared stubs for the agents suite.

The service imports its own packages top-level (`config`, `schemas`, `rag`,
`llm`, `agents`), so the module root has to be on sys.path.

Embeddings and the LLM are stubbed so the suite is deterministic, offline and
free: the real sentence-transformers model and NIM quota stay untouched, and CI
never has to download torch.
"""
import os
import re
import sys
import zlib

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE_ROOT = os.path.dirname(_HERE)

if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

# Keep the real ./data/chroma index out of the tests entirely.
os.environ.setdefault("LLM_PROVIDER", "nim")
os.environ["NIM_API_KEY"] = "test-key-not-real"
os.environ["LLM_API_KEY"] = "test-key-not-real"

_STEM = re.compile(r"[a-z0-9]+")


class StubEmbedder:
    """Deterministic lexical embedder (hashed bag of words).

    Good enough that cosine ranking genuinely reflects word overlap, so
    retrieval-order assertions test real behaviour instead of tautologies.
    """
    dim = 256

    def _vec(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in _STEM.findall(text.lower()):
            # zlib.crc32, not builtin hash(): Python salts string hashing per
            # process, which made retrieval ranking (and these tests) flaky.
            vec[zlib.crc32(token.encode("utf-8")) % self.dim] += 1.0
        return vec

    def encode(self, texts):
        return np.vstack([self._vec(t) for t in texts])

    def encode_single(self, text):
        return self._vec(text)


@pytest.fixture
def stub_embeddings(monkeypatch, tmp_path):
    """Point the vector store at a temp dir and a fake embedder."""
    from config import settings
    from rag import vector_store as vs_module
    from rag.vector_store import VectorStore

    VectorStore._instance = None
    VectorStore._index = None
    VectorStore._documents = None
    VectorStore._id_to_idx = None

    monkeypatch.setattr(vs_module, "EmbeddingModel", StubEmbedder)
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "vs"))

    yield vs_module

    VectorStore._instance = None
    VectorStore._index = None
    VectorStore._documents = None
    VectorStore._id_to_idx = None


@pytest.fixture
def store(stub_embeddings):
    from rag.vector_store import VectorStore
    return VectorStore()


class StubLLM:
    """Stand-in for LLMClient: records prompts, returns a canned answer."""

    def __init__(self, answer="stubbed answer"):
        self.answer = answer
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return self.answer
