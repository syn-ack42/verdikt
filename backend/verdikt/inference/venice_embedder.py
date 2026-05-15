from __future__ import annotations

import httpx
import numpy as np

from verdikt.inference.base import EmbedderBase


class VeniceEmbedder(EmbedderBase):
    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._dimension: int | None = None

    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        text_inputs = [t.decode() if isinstance(t, bytes) else t for t in inputs]
        try:
            resp = httpx.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": text_inputs},
                timeout=120.0,
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(f"Cannot reach Venice API at {self._base_url}.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            if status == 401:
                raise RuntimeError("Venice API key is invalid or expired.") from exc
            raise RuntimeError(f"Venice API returned {status}: {body}") from exc

        data = resp.json()
        vectors = [item["embedding"] for item in data["data"]]
        arr = np.array(vectors, dtype=np.float32)
        if self._dimension is None:
            self._dimension = arr.shape[1]
        return arr

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            result = self.embed(["probe"])
            return result.shape[1]
        return self._dimension
