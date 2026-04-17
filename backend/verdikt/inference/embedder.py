from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

from verdikt.inference.base import EmbedderBase


class SentenceTransformerEmbedder(EmbedderBase):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        texts = [
            inp.decode("utf-8") if isinstance(inp, bytes) else inp
            for inp in inputs
        ]
        return self._model.encode(texts, convert_to_numpy=True).astype(np.float32)

    @property
    def dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()

    @property
    def model_name(self) -> str:
        return self._model_name
