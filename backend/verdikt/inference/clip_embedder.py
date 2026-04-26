from __future__ import annotations

import io

import numpy as np

from verdikt.inference.base import EmbedderBase

_DEFAULT_MODEL = "openai/clip-vit-base-patch32"


class CLIPEmbedder(EmbedderBase):
    """Image embedder using OpenAI CLIP via transformers directly.

    Uses openai/clip-vit-base-patch32 by default. Embedding dimension is 512.
    Accepts image bytes (JPEG/PNG/etc); text inputs are not supported.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        from transformers import CLIPImageProcessor, CLIPModel
        self._model_name = model_name
        # CLIPImageProcessor.from_pretrained bypasses AutoImageProcessor, which requires the
        # newer image_processor_type key absent from openai/clip-vit-base-patch32's config.
        self._processor = CLIPImageProcessor.from_pretrained(model_name)
        self._model = CLIPModel.from_pretrained(model_name)
        self._model.eval()

    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        import torch
        from PIL import Image

        images = []
        for inp in inputs:
            if isinstance(inp, bytes):
                try:
                    images.append(Image.open(io.BytesIO(inp)).convert("RGB"))
                except Exception as exc:
                    raise ValueError(f"Failed to decode image for CLIP embedding: {exc}") from exc
            else:
                raise TypeError(
                    "CLIPEmbedder only accepts image bytes. "
                    "For text projects use SentenceTransformerEmbedder."
                )

        processed = self._processor(images=images, return_tensors="pt")
        with torch.no_grad():
            features = self._model.get_image_features(**processed)
            # L2-normalise so cosine similarity == dot product in ChromaDB
            features = features / features.norm(dim=-1, keepdim=True)

        return features.cpu().numpy().astype(np.float32)

    @property
    def dimension(self) -> int:
        return self._model.config.projection_dim

    @property
    def model_name(self) -> str:
        return self._model_name
