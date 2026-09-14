"""FAISS vector store + retriever behaviour (stubbed embeddings, no torch)."""
import pytest

DOCS = [
    {"id": "d_aadhar", "text": "Aadhaar Number is a 12 digit identity number issued by UIDAI",
     "metadata": {"category": "form_glossary", "field": "aadhar_number"}},
    {"id": "d_pan", "text": "PAN Number is a ten character alphanumeric income tax code",
     "metadata": {"category": "form_glossary", "field": "pan_number"}},
    {"id": "d_focus", "text": "Focus Indicators show keyboard focus outline for keyboard users",
     "metadata": {"category": "accessibility_faq", "topic": "focus_indicators"}},
]


def _seed(store):
    store.add_documents(DOCS)


def test_empty_store_reports_zero(store):
    assert store.count() == 0
    assert store.query("aadhaar number") == []


def test_add_documents_increments_count(store):
    _seed(store)
    assert store.count() == 3


def test_query_ranks_most_relevant_document_first(store):
    """Word overlap must drive ranking - otherwise RAG is silently random."""
    _seed(store)
    results = store.query("what is the aadhaar number", k=3)
    assert results[0]["id"] == "d_aadhar"


def test_query_respects_top_k(store):
    _seed(store)
    assert len(store.query("aadhaar number", k=2)) == 2


def test_query_k_larger_than_index_does_not_crash(store):
    _seed(store)
    assert len(store.query("aadhaar number", k=50)) == 3


def test_results_carry_distance_and_metadata(store):
    _seed(store)
    hit = store.query("aadhaar number", k=1)[0]
    assert hit["metadata"]["field"] == "aadhar_number"
    assert isinstance(hit["distance"], float)


def test_persistence_survives_reload(store, stub_embeddings):
    from rag.vector_store import VectorStore
    _seed(store)

    reloaded = VectorStore()
    assert reloaded.count() == 3
    assert reloaded.query("aadhaar number", k=1)[0]["id"] == "d_aadhar"


def test_reset_clears_index_and_files(store):
    _seed(store)
    store.reset()
    assert store.count() == 0
    assert store.query("aadhaar number") == []


def test_add_documents_handles_empty_list(store):
    store.add_documents([])
    assert store.count() == 0


# --- retriever --------------------------------------------------------------

def test_retriever_returns_requested_top_k(store):
    from rag.retriever import Retriever
    _seed(store)
    docs = Retriever().retrieve("aadhaar number", k=2)
    assert len(docs) == 2


def test_format_sources_includes_category_and_label(store):
    from rag.retriever import Retriever
    _seed(store)
    r = Retriever()
    text = r.format_sources(r.retrieve("aadhaar number", k=1))
    assert "[form_glossary:aadhar_number]" in text


def test_format_sources_without_results_is_explicit(store):
    from rag.retriever import Retriever
    assert Retriever().format_sources([]) == "No relevant documents found."


def test_get_source_ids_skips_unnamed_docs(store):
    from rag.retriever import Retriever
    _seed(store)
    r = Retriever()
    ids = r.get_source_ids(r.retrieve("aadhaar number", k=3))
    assert ids[0] == "d_aadhar"
    assert all(isinstance(i, str) and i for i in ids)
