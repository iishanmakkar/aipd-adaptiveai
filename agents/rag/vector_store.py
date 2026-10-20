import numpy as np
import hashlib
import json
import os
import threading
from pathlib import Path
from config import settings
from .embeddings import EmbeddingModel
import uuid

try:
    import faiss
except ImportError:
    # Some hosts block the unsigned faiss native DLL (e.g. Windows Smart App
    # Control). The exact-search fallback below computes identical results,
    # so the store keeps working without it.
    faiss = None

# Service root (the agents/ package lives here): CWD-relative settings must
# resolve against this, not os.getcwd(), or launching from another directory
# silently creates a second empty store.
_SERVICE_ROOT = Path(__file__).resolve().parent.parent

# Guards add/query/save/reset/load: without it two concurrent writers
# interleave start_idx/_id_to_idx/_documents, and a query can read torn JSON.
# RLock: _load_or_create -> _re_embed_all -> _save nest.
_LOCK = threading.RLock()


def _normalize_l2(vectors: np.ndarray) -> np.ndarray:
    vectors = np.ascontiguousarray(vectors, dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


class _NumpyFlatIndex:
    """Exact inner-product index over L2-normalized vectors — the same math
    faiss.IndexFlatIP performs (brute-force dot products), kept in-process."""

    def __init__(self, dim: int):
        self.dim = dim
        self._vectors = np.zeros((0, dim), dtype="float32")

    @property
    def ntotal(self) -> int:
        return int(self._vectors.shape[0])

    def add(self, vectors: np.ndarray) -> None:
        if self.ntotal == 0 and self.dim == 0:
            self.dim = vectors.shape[1]
        if vectors.shape[1] != self.dim:
            raise ValueError(f"vector dim {vectors.shape[1]} != index dim {self.dim}")
        if self.ntotal:
            self._vectors = np.vstack([self._vectors, vectors])
        else:
            self._vectors = vectors.copy()

    def search(self, query: np.ndarray, k: int):
        scores = self._vectors @ query[0]
        order = np.argsort(-scores)[:k]
        return scores[order].reshape(1, -1), order.reshape(1, -1)


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
            raw = Path(settings.CHROMA_PERSIST_DIR)
            self.persist_dir = (raw if raw.is_absolute()
                                else (_SERVICE_ROOT / raw)).resolve()
            self.persist_dir.mkdir(parents=True, exist_ok=True)

            # Filenames are fixed constants, but resolve + containment makes the
            # invariant explicit: nothing can ever escape persist_dir.
            def _within(name: str) -> Path:
                p = (self.persist_dir / name).resolve()
                if not p.is_relative_to(self.persist_dir):
                    raise ValueError(f"refusing to touch path outside persist dir: {name}")
                return p

            self.index_path = _within("faiss.index")
            self.npy_path = _within("vectors.npy")
            self.docs_path = _within("documents.json")
            self.mapping_path = _within("id_mapping.json")

            self._embedding_model = EmbeddingModel()
            self._load_or_create()

    def _read_json(self, path: Path):
        """Tolerant JSON read: missing/corrupt files come back None (the
        caller rebuilds) instead of crashing the boot."""
        try:
            if path.exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _write_atomic(self, path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _new_index(self, dim: int):
        if faiss is not None:
            return faiss.IndexFlatIP(dim)
        return _NumpyFlatIndex(dim)

    def _load_or_create(self):
        with _LOCK:
            dim = int(self._embedding_model.encode_single("test").shape[0])
            docs = self._read_json(self.docs_path)
            mapping = self._read_json(self.mapping_path)
            self._documents = docs if isinstance(docs, list) else []
            self._id_to_idx = mapping if isinstance(mapping, dict) else {}
            if faiss is not None:
                index = None
                if self.index_path.exists():
                    try:
                        index = faiss.read_index(str(self.index_path))
                    except Exception:
                        index = None
                self._index = index
                self._validate_or_rebuild(dim)
                # A vectors.npy left over from a faiss-less run is now stale.
                if self.npy_path.exists():
                    self.npy_path.unlink()
            else:
                vectors = None
                if self.npy_path.exists():
                    try:
                        loaded = np.load(self.npy_path)
                        vectors = (loaded if isinstance(loaded, np.ndarray)
                                   and loaded.ndim == 2 and loaded.shape[1] > 0
                                   else None)
                    except Exception:
                        vectors = None
                if vectors is None:
                    self._index = None
                else:
                    index = _NumpyFlatIndex(vectors.shape[1])
                    try:
                        index.add(vectors)
                    except Exception:
                        index = None
                    self._index = index
                self._validate_or_rebuild(dim)
                # A faiss.index we can no longer read would silently diverge
                # from documents.json, so remove it when on the numpy store.
                if self.index_path.exists():
                    self.index_path.unlink()
            self._save_locked()

    def _validate_or_rebuild(self, dim: int) -> None:
        """Repair a loaded store that disagrees with itself instead of serving
        wrong documents: rebuild the id map from the documents (ids live in
        each document), and re-embed when there is no usable index or the
        persisted dimension no longer matches the embedding model (e.g.
        EMBEDDING_MODEL changed, or a faiss<->numpy format switch orphaned
        one backend's files). Document TEXT is never discarded here."""
        if self._index is None:
            self._re_embed_all(dim)
            return
        index_dim = (self._index.d if faiss is not None
                     else self._index.dim)
        if index_dim != dim or self._index.ntotal != len(self._documents):
            self._re_embed_all(dim)
            return
        rebuilt = {d["id"]: i for i, d in enumerate(self._documents)
                   if isinstance(d, dict) and "id" in d}
        if rebuilt != self._id_to_idx:
            self._id_to_idx = rebuilt

    def _re_embed_all(self, dim: int) -> None:
        """Keep the document TEXT (still valid), rebuild vectors + mapping."""
        valid = [d for d in self._documents
                 if isinstance(d, dict) and "id" in d and "text" in d]
        self._documents = valid
        self._id_to_idx = {d["id"]: i for i, d in enumerate(valid)}
        self._index = self._new_index(dim)
        if valid:
            embeddings = _normalize_l2(
                self._embedding_model.encode(
                    [d["text"] for d in valid]).astype("float32"))
            self._index.add(embeddings)
        self._save_locked()

    def _save(self) -> None:
        """Locked entry point for callers outside _load_or_create."""
        with _LOCK:
            self._save_locked()

    def _save_locked(self):
        # Atomic writes (tmp + replace): a kill mid-save must never leave a
        # truncated documents.json that crashes the next boot, or an
        # index/mapping pair from two different generations.
        # index_path/docs_path/mapping_path are resolved + containment-checked
        # in __init__ (they can never leave persist_dir).
        if faiss is not None:
            faiss.write_index(self._index, str(self.index_path) + ".tmp")
            os.replace(str(self.index_path) + ".tmp", str(self.index_path))
            # A vectors.npy left over from a faiss-less run is now stale.
            if self.npy_path.exists():
                self.npy_path.unlink()
        else:
            # np.save appends ".npy" when missing, so the tmp name keeps it.
            npy_tmp = self.npy_path.with_name(self.npy_path.name + ".tmp.npy")
            np.save(npy_tmp, self._index._vectors)
            os.replace(npy_tmp, self.npy_path)
            # A faiss.index we can no longer read would silently diverge from
            # documents.json, so remove it when switching to the numpy store.
            if self.index_path.exists():
                self.index_path.unlink()
        self._write_atomic(self.docs_path,
                           json.dumps(self._documents).encode("utf-8"))
        self._write_atomic(self.mapping_path,
                           json.dumps(self._id_to_idx).encode("utf-8"))

    def add_documents(self, documents: list[dict]) -> None:
        if not documents:
            return

        with _LOCK:
            # De-duplicate: re-submitting an id must not append a stale twin
            # (the mapping would point at the newest copy while query() still
            # serves the old text, and count() inflates without bound).
            fresh = [d for d in documents
                     if d.get("id", None) not in self._id_to_idx]
            # ...except id-less docs, which always get a fresh uuid below.
            fresh += [d for d in documents if "id" not in d]
            seen: set[str] = set()
            unique = []
            for d in fresh:
                if "id" in d:
                    if d["id"] in seen:
                        continue
                    seen.add(d["id"])
                unique.append(d)
            if not unique:
                return
            texts = [doc["text"] for doc in unique]
            embeddings = self._embedding_model.encode(texts).astype('float32')
            # Normalize for cosine similarity
            embeddings = _normalize_l2(embeddings)

            start_idx = len(self._documents)
            for i, doc in enumerate(unique):
                doc_id = doc.get("id", str(uuid.uuid4()))
                self._id_to_idx[doc_id] = start_idx + i
                self._documents.append({
                    "id": doc_id,
                    "text": doc["text"],
                    "metadata": doc.get("metadata", {})
                })

            self._index.add(embeddings)
            self._save_locked()

    def query(self, query_text: str, k: int = None) -> list[dict]:
        if k is None:
            k = settings.TOP_K

        with _LOCK:
            if self._index.ntotal == 0:
                return []

            query_embedding = self._embedding_model.encode_single(query_text).astype('float32').reshape(1, -1)
            query_embedding = _normalize_l2(query_embedding)

            scores, indices = self._index.search(query_embedding, min(k, self._index.ntotal))

            docs = []
            for score, idx in zip(scores[0], indices[0]):
                if 0 <= idx < len(self._documents):
                    doc = self._documents[int(idx)].copy()
                    # float32 dot products can exceed 1.0 by an ulp for
                    # identical vectors: clamp so "distance" never goes
                    # negative and downstream thresholds keep working.
                    doc["distance"] = max(0.0, float(1.0 - score))
                    docs.append(doc)
            return docs

    def get_document(self, doc_id: str):
        """A copy of one stored document (text + metadata) or None."""
        with _LOCK:
            idx = self._id_to_idx.get(doc_id)
            if idx is None or idx >= len(self._documents):
                return None
            doc = self._documents[idx]
            if not isinstance(doc, dict):
                return None
            return {"id": doc.get("id"), "text": doc.get("text", ""),
                    "metadata": dict(doc.get("metadata", {}) or {})}

    def update_document_text(self, doc_id: str, text: str, metadata=None) -> bool:
        """Replace one document's text in place and rebuild vectors. Used by
        the seed sync when a seed's wording was corrected after indexing."""
        with _LOCK:
            idx = self._id_to_idx.get(doc_id)
            if idx is None or idx >= len(self._documents):
                return False
            self._documents[idx]["text"] = text
            if metadata is not None:
                self._documents[idx]["metadata"] = metadata
            dim = int(self._embedding_model.encode_single("test").shape[0])
            self._re_embed_all(dim)
            self._save_locked()
            return True

    def count(self) -> int:
        with _LOCK:
            return self._index.ntotal if self._index else 0

    def doc_ids(self) -> set[str]:
        """Ids already indexed - lets callers add what is missing instead of
        re-embedding the whole corpus on every boot."""
        with _LOCK:
            return set(self._id_to_idx.keys()) if self._id_to_idx else set()

    def reset(self) -> None:
        with _LOCK:
            for path in (self.index_path, self.npy_path, self.docs_path, self.mapping_path):
                if path.exists():
                    path.unlink()
            self._load_or_create()
