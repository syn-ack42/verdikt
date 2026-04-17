from abc import ABC, abstractmethod

import numpy as np


class EmbedderBase(ABC):
    """Base class for embedding models (text, image, audio)."""

    @abstractmethod
    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        """Return an (n, dim) float32 embedding matrix."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the output vectors."""
