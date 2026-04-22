from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from verdikt.api.app import create_app
from verdikt.api.deps import get_engine, get_session
from verdikt.core.models import Chunk, Domain, MaterialItem, Project, RatingDimension
from verdikt.inference.base import EmbedderBase
from verdikt.storage.base import VectorStore
from verdikt.storage.orm import Base
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore


# ── Test doubles ─────────────────────────────────────────────────────────────

class MockEmbedder(EmbedderBase):
    _DIM = 8

    def embed(self, inputs: list[str | bytes]) -> np.ndarray:
        rng = np.random.default_rng(42)
        return rng.random((len(inputs), self._DIM)).astype(np.float32)

    @property
    def dimension(self) -> int:
        return self._DIM

    @property
    def model_name(self) -> str:
        return "mock"


class MockVectorStore(VectorStore):
    def __init__(self) -> None:
        self.upserted: list[str] = []

    def upsert(self, item_id: str, embedding: list[float], metadata: dict) -> None:
        self.upserted.append(item_id)

    def query(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        return []

    def delete_collection(self) -> None:
        self.upserted.clear()

    def delete_items(self, ids: list[str]) -> None:
        self.upserted = [i for i in self.upserted if i not in ids]


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(mem_engine):
    app = create_app()

    def override_engine():
        return mem_engine

    def override_session():
        with Session(mem_engine) as s:
            yield s

    app.dependency_overrides[get_engine] = override_engine
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


@pytest.fixture
def project_id(client) -> str:
    resp = client.post("/api/projects", json={
        "name": "Test Project",
        "domain": "text",
        "rating_dimensions": [
            {"name": "Prose", "description": "Writing style", "weight": 1.0},
        ],
        "crystallisation_threshold": 2,
    })
    assert resp.status_code == 201
    return resp.json()["id"]


# ── Project CRUD ──────────────────────────────────────────────────────────────

def test_create_and_list_projects(client):
    client.post("/api/projects", json={"name": "Alpha", "domain": "text"})
    client.post("/api/projects", json={"name": "Beta", "domain": "text"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "Alpha" in names
    assert "Beta" in names


def test_get_project(client, project_id):
    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id


def test_get_project_404(client):
    resp = client.get("/api/projects/nonexistent")
    assert resp.status_code == 404


def test_delete_project(client, project_id):
    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 204
    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 404


# ── Rating ────────────────────────────────────────────────────────────────────

@pytest.fixture
def clustered_chunk(client, project_id, mem_engine):
    """Insert a chunk with cluster_id directly into the DB."""
    with Session(mem_engine) as s:
        chunk = Chunk(
            project_id=project_id,
            material_item_id="m_dummy",
            content="A long enough passage to rate.",
            position=0,
            size=7,
            cluster_id=0,
        )
        SQLiteChunkStore(s).save_many([chunk])
        s.commit()
    return chunk


def test_submit_rating(client, project_id, clustered_chunk):
    resp = client.post(f"/api/projects/{project_id}/ratings", json={
        "chunk_id": clustered_chunk.id,
        "material_item_id": "m_dummy",
        "dimension_scores": {"Prose": 4.0},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["chunk_id"] == clustered_chunk.id
    assert data["dimension_scores"]["Prose"] == 4.0


def test_get_next_chunk(client, project_id, clustered_chunk):
    resp = client.get(f"/api/projects/{project_id}/ratings/next")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunk"]["id"] == clustered_chunk.id
    assert "total_chunks" in data
    assert "total_rated" in data


def test_next_chunk_404_when_all_rated(client, project_id, clustered_chunk):
    client.post(f"/api/projects/{project_id}/ratings", json={
        "chunk_id": clustered_chunk.id,
        "material_item_id": "m_dummy",
        "dimension_scores": {"Prose": 4.0},
    })
    resp = client.get(f"/api/projects/{project_id}/ratings/next")
    assert resp.status_code == 404


def test_list_ratings(client, project_id, clustered_chunk):
    client.post(f"/api/projects/{project_id}/ratings", json={
        "chunk_id": clustered_chunk.id,
        "material_item_id": "m_dummy",
        "dimension_scores": {"Prose": 5.0},
    })
    resp = client.get(f"/api/projects/{project_id}/ratings")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── Profile ───────────────────────────────────────────────────────────────────

@pytest.fixture
def saved_profile(project_id, mem_engine):
    """Insert a profile row directly (bypasses Ollama)."""
    from verdikt.core.models import DimensionProfile, PreferenceProfile
    from verdikt.storage.sqlite import SQLiteProfileStore
    with Session(mem_engine) as s:
        p = PreferenceProfile(
            project_id=project_id,
            version=1,
            dimensions=[DimensionProfile(name="Prose", description="d", summary="s", typical_score=3.5)],
            overall_summary="Likes prose.",
            rating_count=5,
        )
        SQLiteProfileStore(s).save(p)
        s.commit()
    return p


def test_get_profile_404_when_none(client, project_id):
    resp = client.get(f"/api/projects/{project_id}/profile")
    assert resp.status_code == 404


def test_crystallise_below_threshold_422(client, project_id, clustered_chunk):
    # threshold is 2, submit only 1 rating
    client.post(f"/api/projects/{project_id}/ratings", json={
        "chunk_id": clustered_chunk.id,
        "material_item_id": "m_dummy",
        "dimension_scores": {"Prose": 3.0},
    })
    resp = client.post(f"/api/projects/{project_id}/profile/crystallise")
    assert resp.status_code == 422


def test_crystallise_status_not_running(client, project_id):
    resp = client.get(f"/api/projects/{project_id}/profile/crystallise/status")
    assert resp.status_code == 200
    assert resp.json() == {"running": False}


def test_get_profile_versions(client, project_id, saved_profile, mem_engine):
    # Add a second version
    from verdikt.core.models import DimensionProfile, PreferenceProfile
    from verdikt.storage.sqlite import SQLiteProfileStore
    with Session(mem_engine) as s:
        p2 = PreferenceProfile(
            project_id=project_id,
            version=2,
            dimensions=[DimensionProfile(name="Prose", description="d", summary="s2", typical_score=4.0)],
            overall_summary="Revised.",
            rating_count=10,
        )
        SQLiteProfileStore(s).save(p2)
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/profile/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2  # descending order


def test_update_profile_creates_new_version(client, project_id, saved_profile):
    resp = client.put(f"/api/projects/{project_id}/profile", json={
        "overall_summary": "Updated summary.",
        "dimensions": [{"name": "Prose", "description": "d", "summary": "new", "typical_score": 3.5}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == saved_profile.version + 1
    assert data["overall_summary"] == "Updated summary."
    assert data["id"] != saved_profile.id

    # Original version still exists
    versions_resp = client.get(f"/api/projects/{project_id}/profile/versions")
    assert len(versions_resp.json()) == 2


def test_restore_profile_version(client, project_id, saved_profile, mem_engine):
    # Create v2 so we can restore v1
    from verdikt.core.models import DimensionProfile, PreferenceProfile
    from verdikt.storage.sqlite import SQLiteProfileStore
    with Session(mem_engine) as s:
        p2 = PreferenceProfile(
            project_id=project_id,
            version=2,
            dimensions=[DimensionProfile(name="Prose", description="d", summary="v2", typical_score=4.0)],
            overall_summary="Version 2.",
            rating_count=10,
        )
        SQLiteProfileStore(s).save(p2)
        s.commit()

    # Restore v1
    resp = client.post(f"/api/projects/{project_id}/profile/versions/{saved_profile.id}/restore")
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == 3
    assert data["overall_summary"] == saved_profile.overall_summary
    assert data["id"] != saved_profile.id

    versions_resp = client.get(f"/api/projects/{project_id}/profile/versions")
    assert len(versions_resp.json()) == 3


def test_restore_profile_version_404(client, project_id, saved_profile):
    resp = client.post(f"/api/projects/{project_id}/profile/versions/nonexistent/restore")
    assert resp.status_code == 404


# ── Work deletion cascade ─────────────────────────────────────────────────────

@pytest.fixture
def work_with_rating(client, project_id, mem_engine):
    """Insert a material item, a chunk, and a rating for that chunk."""
    from verdikt.core.models import Chunk, Rating
    from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteRatingStore

    with Session(mem_engine) as s:
        chunk = Chunk(
            project_id=project_id,
            material_item_id="mat_cascade",
            content="Some text.",
            position=0,
            size=2,
            cluster_id=0,
        )
        SQLiteChunkStore(s).save_many([chunk])

        rating = Rating(
            project_id=project_id,
            chunk_id=chunk.id,
            material_item_id="mat_cascade",
            dimension_scores={"Prose": 4.0},
        )
        SQLiteRatingStore(s).save(rating)

        # Insert a minimal material item row so the delete endpoint can find it
        from verdikt.storage.orm import MaterialItemRow
        from datetime import datetime, timezone
        s.add(MaterialItemRow(
            id="mat_cascade",
            project_id=project_id,
            project_seq=99,
            source_plugin="filedrop",
            source_path="/fake/path.txt",
            content=b"Some text.",
            content_is_bytes=False,
            domain="text",
            content_type="text/plain",
            pipeline_phase="ingested",
            ingested_at=datetime.now(timezone.utc),
        ))
        s.commit()
    return chunk, rating


def test_delete_work_removes_ratings(client, project_id, work_with_rating):
    chunk, rating = work_with_rating

    # Confirm rating exists
    resp = client.get(f"/api/projects/{project_id}/ratings")
    assert any(r["id"] == rating.id for r in resp.json())

    # Delete the work by sequence number
    resp = client.delete(f"/api/projects/{project_id}/works/99")
    assert resp.status_code == 204

    # Rating must be gone
    resp = client.get(f"/api/projects/{project_id}/ratings")
    assert not any(r["id"] == rating.id for r in resp.json())


# ── Plugin API ────────────────────────────────────────────────────────────────

def test_list_plugins(client):
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "storage" in names
    assert "ao3" in names
    for p in resp.json():
        assert "config_schema" in p
        assert "title" in p


def test_get_plugin_config_none_when_absent(client, project_id):
    resp = client.get(f"/api/projects/{project_id}/works/plugin-config")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_save_and_get_plugin_config(client, project_id):
    body = {"plugin_name": "ao3", "config": {"username": "u", "password": "p", "max_works": 5}}
    resp = client.put(f"/api/projects/{project_id}/works/plugin-config", json=body)
    assert resp.status_code == 200
    assert resp.json()["plugin_name"] == "ao3"
    assert resp.json()["config"]["username"] == "u"

    resp2 = client.get(f"/api/projects/{project_id}/works/plugin-config")
    assert resp2.status_code == 200
    assert resp2.json()["ao3"]["plugin_name"] == "ao3"


def test_save_plugin_config_unknown_plugin(client, project_id):
    body = {"plugin_name": "no_such_plugin", "config": {}}
    resp = client.put(f"/api/projects/{project_id}/works/plugin-config", json=body)
    assert resp.status_code == 422


def test_ingest_plugin_storage(mem_engine, tmp_path):
    from verdikt.api.deps import get_engine, get_session, get_storage
    from verdikt.storage.files import LocalStorageBackend
    app = create_app()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "sample.txt").write_text("Hello world content for testing plugin ingest.")

    def override_engine():
        return mem_engine
    def override_session():
        with Session(mem_engine) as s:
            yield s
    def override_storage():
        return LocalStorageBackend(storage_root)

    app.dependency_overrides[get_engine] = override_engine
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage] = override_storage
    client = TestClient(app)

    # Create project
    proj_resp = client.post("/api/projects", json={"name": "T", "domain": "text", "rating_dimensions": [{"name": "Q", "description": "d", "weight": 1.0}]})
    pid = proj_resp.json()["id"]

    body = {"plugin_name": "storage", "config": {"selections": [{"path": "/sample.txt", "mode": "file"}]}}
    resp = client.post(f"/api/projects/{pid}/works/ingest-plugin", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert data["added"] == 1

    items = client.get(f"/api/projects/{pid}/works").json()
    assert any("sample" in (w.get("source_path") or "") for w in items)


def test_ingest_plugin_no_config_returns_422(client, project_id):
    resp = client.post(
        f"/api/projects/{project_id}/works/ingest-plugin",
        json={"plugin_name": "ao3"},
    )
    assert resp.status_code == 422


def test_update_plugin_no_config_returns_error_event(client, project_id):
    with client.stream("POST", f"/api/projects/{project_id}/works/update-plugin/stream") as resp:
        assert resp.status_code == 200
        body = resp.read().decode()
    assert '"error"' in body
