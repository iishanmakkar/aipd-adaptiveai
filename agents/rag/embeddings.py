from sentence_transformers import SentenceTransformer
from config import settings
import numpy as np


class EmbeddingModel:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._model is None:
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(texts, convert_to_numpy=True)

    def encode_single(self, text: str) -> np.ndarray:
        return self._model.encode([text], convert_to_numpy=True)[0]