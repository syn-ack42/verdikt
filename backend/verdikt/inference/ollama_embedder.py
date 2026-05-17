from __future__ import annotations

import numpy as np
import httpx

from verdikt.inference.base import EmbedderBase


class OllamaEmbedder(EmbedderBase):
    """Embedding via Ollama's /api/embed endpoint.

    Ollama supports dedicated embedding models (e.g. nomic-embed-text, mxbai-embed-large)
    and can embed with any model that has an embedding layer.
    """

    def __init__(self, model_name: str, base_url: str, api_key: str | None = None) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._dim: int | None = None

    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        texts = [inp.decode("utf-8") if isinstance(inp, bytes) else inp for inp in inputs]
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        resp = httpx.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model_name, "input": texts},
            headers=headers,
            timeout=120.0,
        )
        resp.raise_for_status()
        vecs = resp.json()["embeddings"]
        arr = np.array(vecs, dtype=np.float32)
        if self._dim is None:
            self._dim = arr.shape[1]
        return arr

    @property
    def dimension(self) -> int:
        if self._dim is None:
            # Probe with a single string to discover dimensionality
            self.embed(["probe"])
        return self._dim  # type: ignore[return-value]

    @property
    def model_name(self) -> str:
        return self._model_name
