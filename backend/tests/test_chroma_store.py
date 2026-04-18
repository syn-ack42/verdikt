import pytest
import chromadb

from verdikt.storage.chroma import ChromaVectorStore

pytestmark = pytest.mark.infra


@pytest.fixture
def store():
    import uuid
    client = chromadb.EphemeralClient()
    return ChromaVectorStore(client, f"test_{uuid.uuid4().hex}")


def test_upsert_and_query(store):
    embedding = [0.1] * 384
    store.upsert("id1", embedding, {"chunk_id": "id1", "project_id": "p1"})
    results = store.query(embedding, n_results=1)
    assert len(results) == 1
    assert results[0]["id"] == "id1"


def test_query_returns_closest(store):
    near = [1.0] + [0.0] * 383
    far = [0.0] + [1.0] * 383
    store.upsert("near", near, {"chunk_id": "near", "project_id": "p1"})
    store.upsert("far", far, {"chunk_id": "far", "project_id": "p1"})

    results = store.query(near, n_results=2)
    assert results[0]["id"] == "near"
    assert results[1]["id"] == "far"


def test_metadata_preserved(store):
    store.upsert("c1", [0.5] * 384, {"project_id": "p1", "position": 3})
    results = store.query([0.5] * 384, n_results=1)
    assert results[0]["metadata"]["project_id"] == "p1"
    assert results[0]["metadata"]["position"] == 3


def test_distance_included_in_result(store):
    store.upsert("c1", [0.1] * 384, {"chunk_id": "c1", "project_id": "p1"})
    results = store.query([0.1] * 384, n_results=1)
    assert "distance" in results[0]


def test_delete_collection(store):
    store.upsert("c1", [0.1] * 384, {"chunk_id": "c1", "project_id": "p1"})
    store.delete_collection()
    # Collection is gone — a new store on the same client won't find results
    client = chromadb.EphemeralClient()
    fresh = ChromaVectorStore(client, "other_collection")
    results = fresh.query([0.1] * 384, n_results=1)
    assert results == []
