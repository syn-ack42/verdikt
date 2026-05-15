"""Unit tests for VeniceEmbedder — all HTTP calls mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from verdikt.inference.venice_embedder import VeniceEmbedder


BASE_URL = "https://api.venice.ai/api/v1"
MODEL = "text-embedding-bge-m3"
API_KEY = "sk-test-key"


def _embedder() -> VeniceEmbedder:
    return VeniceEmbedder(BASE_URL, MODEL, API_KEY)


def _embed_response(vectors: list[list[float]]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [{"embedding": v} for v in vectors],
        "model": MODEL,
    }
    return resp


# ── embed ─────────────────────────────────────────────────────────────────────

def test_embed_returns_correct_shape():
    vecs = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=_embed_response(vecs)):
        arr = _embedder().embed(["hello", "world"])
    assert arr.shape == (2, 3)
    assert arr.dtype == np.float32


def test_embed_sends_correct_payload():
    vecs = [[0.1, 0.2]]
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=_embed_response(vecs)) as mock_post:
        _embedder().embed(["test input"])

    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["model"] == MODEL
    assert call_kwargs["json"]["input"] == ["test input"]
    assert call_kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert "embeddings" in mock_post.call_args[0][0]


def test_embed_bytes_decoded_to_str():
    vecs = [[0.1, 0.2]]
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=_embed_response(vecs)) as mock_post:
        _embedder().embed([b"byte input"])

    sent = mock_post.call_args[1]["json"]["input"]
    assert sent == ["byte input"]


def test_embed_caches_dimension():
    vecs = [[0.1, 0.2, 0.3]]
    emb = _embedder()
    assert emb._dimension is None
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=_embed_response(vecs)):
        emb.embed(["test"])
    assert emb._dimension == 3


# ── error handling ────────────────────────────────────────────────────────────

def test_embed_empty_data_raises():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [], "model": MODEL}
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=resp):
        with pytest.raises(RuntimeError, match="no vectors"):
            _embedder().embed(["test"])


def test_embed_missing_data_key_raises():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"model": MODEL}  # no "data" key
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=resp):
        with pytest.raises(RuntimeError, match="no vectors"):
            _embedder().embed(["test"])


def test_embed_malformed_item_raises():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [{"wrong_key": [0.1]}]}  # no "embedding" key
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=resp):
        with pytest.raises(RuntimeError, match="unexpected shape"):
            _embedder().embed(["test"])


def test_embed_401_raises_key_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    exc = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
    with patch("verdikt.inference.venice_embedder.httpx.post", side_effect=exc):
        with pytest.raises(RuntimeError, match="Venice API key is invalid"):
            _embedder().embed(["test"])


def test_embed_connect_error_raises():
    with patch("verdikt.inference.venice_embedder.httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(RuntimeError, match="Cannot reach Venice API"):
            _embedder().embed(["test"])


def test_embed_generic_http_error_includes_status():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal server error"
    exc = httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
    with patch("verdikt.inference.venice_embedder.httpx.post", side_effect=exc):
        with pytest.raises(RuntimeError, match="500"):
            _embedder().embed(["test"])


# ── dimension property ────────────────────────────────────────────────────────

def test_dimension_property_probes_if_unknown():
    vecs = [[0.1, 0.2, 0.3, 0.4]]
    emb = _embedder()
    with patch("verdikt.inference.venice_embedder.httpx.post", return_value=_embed_response(vecs)):
        dim = emb.dimension
    assert dim == 4


def test_dimension_property_uses_cache():
    emb = _embedder()
    emb._dimension = 768
    with patch("verdikt.inference.venice_embedder.httpx.post") as mock_post:
        dim = emb.dimension
    mock_post.assert_not_called()
    assert dim == 768
