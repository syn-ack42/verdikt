from __future__ import annotations

import io

import numpy as np
from sentence_transformers import SentenceTransformer

from verdikt.inference.base import EmbedderBase


class SentenceTransformerEmbedder(EmbedderBase):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        from PIL import Image

        encoded: list = []
        for inp in inputs:
            if isinstance(inp, bytes):
                # Image bytes — CLIP models expect PIL Images
                try:
                    encoded.append(Image.open(io.BytesIO(inp)).convert("RGB"))
                except Exception as exc:
                    raise ValueError(
                        f"Failed to decode image bytes for embedding: {exc}. "
                        "Ensure the project domain is set correctly."
                    ) from exc
            else:
                encoded.append(inp)

        return self._model.encode(encoded, convert_to_numpy=True).astype(np.float32)

    @property
    def dimension(self) -> int:
        return self._model.get_embedding_dimension()

    @property
    def model_name(self) -> str:
        return self._model_name
