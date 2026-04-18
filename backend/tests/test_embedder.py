import numpy as np
import pytest

from verdikt.inference.embedder import SentenceTransformerEmbedder

pytestmark = pytest.mark.infra


@pytest.fixture(scope="module")
def embedder():
    return SentenceTransformerEmbedder()


def test_embed_returns_correct_shape(embedder):
    result = embedder.embed(["hello", "world"])
    assert result.shape == (2, embedder.dimension)


def test_embed_single_input(embedder):
    result = embedder.embed(["one sentence"])
    assert result.shape == (1, embedder.dimension)


def test_dimension_matches_output(embedder):
    result = embedder.embed(["test"])
    assert result.shape[1] == embedder.dimension


def test_embed_dtype_is_float32(embedder):
    result = embedder.embed(["test"])
    assert result.dtype == np.float32


def test_embed_bytes_input(embedder):
    result = embedder.embed([b"hello world"])
    assert result.shape == (1, embedder.dimension)
    assert result.dtype == np.float32


def test_model_name_property(embedder):
    assert embedder.model_name == "all-MiniLM-L6-v2"
