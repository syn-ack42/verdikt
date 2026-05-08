from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from verdikt.api.app import create_app
from verdikt.api.deps import get_auth_session, get_current_user, get_session, get_storage
from verdikt.storage.auth_orm import AuthBase
from verdikt.core.models import Chunk, Domain, MaterialItem, Project, RatingDimension
from verdikt.core.user_models import AuthenticatedUser
from verdikt.inference.base import EmbedderBase
from verdikt.storage.base import VectorStore
from verdikt.storage.files import LocalStorageBackend
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
def mem_auth_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AuthBase.metadata.create_all(engine)
    return engine


_MOCK_USER = AuthenticatedUser(id="test-user-id", email="test@test.com", is_admin=True, db_key="testkey")


@pytest.fixture
def client(mem_engine, mem_auth_engine, tmp_path):
    app = create_app()

    def override_session():
        with Session(mem_engine) as s:
            yield s

    def override_auth_session():
        with Session(mem_auth_engine) as s:
            yield s

    def override_user():
        return _MOCK_USER

    def override_storage():
        yield LocalStorageBackend(tmp_path / "files")

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_session] = override_auth_session
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_storage] = override_storage
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
    data = resp.json()
    assert data["running"] is False


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


def test_ingest_plugin_storage(mem_engine, mem_auth_engine, tmp_path):
    from verdikt.storage.files import LocalStorageBackend
    app = create_app()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    (storage_root / "sample.txt").write_text("Hello world content for testing plugin ingest.")

    def override_session():
        with Session(mem_engine) as s:
            yield s
    def override_auth_session():
        with Session(mem_auth_engine) as s:
            yield s
    def override_user():
        return _MOCK_USER
    def override_storage():
        return LocalStorageBackend(storage_root)

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_session] = override_auth_session
    app.dependency_overrides[get_current_user] = override_user
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

    items = client.get(f"/api/projects/{pid}/works").json()["items"]
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


# ── AI Rating endpoints ───────────────────────────────────────────────────────

import verdikt.api.routers.ai_rating as _ai_rating_module


@pytest.fixture
def ai_rated_chunk(client, project_id, mem_engine):
    """Insert a chunk and an AI rating for it."""
    from datetime import datetime, timezone

    from verdikt.core.models import Chunk, Rating
    from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteRatingStore

    with Session(mem_engine) as s:
        chunk = Chunk(
            project_id=project_id,
            material_item_id="m_ai",
            content="AI rated content.",
            position=0,
            size=4,
            cluster_id=0,
        )
        SQLiteChunkStore(s).save_many([chunk])

        rating = Rating(
            project_id=project_id,
            chunk_id=chunk.id,
            material_item_id="m_ai",
            dimension_scores={"Prose": 3.7},
            is_ai=True,
            rated_at=datetime.now(timezone.utc),
        )
        SQLiteRatingStore(s).save(rating)
        s.commit()

    return chunk, rating


def test_ai_rating_start_202(client, project_id, saved_profile, mem_engine, monkeypatch):
    """POST /start returns 202 and spawns the background thread."""
    from unittest.mock import MagicMock, patch

    monkeypatch.setattr(_ai_rating_module, "_stop_flags", {})
    monkeypatch.setattr(_ai_rating_module, "_status", {})

    class _NopAIRater:
        def __init__(self, **kw): pass
        def run(self, *a, **kw): return iter([])

    with patch.object(_ai_rating_module, "_chromadb", MagicMock()), \
         patch.object(_ai_rating_module, "ChromaVectorStore", MagicMock()), \
         patch("verdikt.inference.resolver.resolve_embedder", return_value=MagicMock()), \
         patch.object(_ai_rating_module, "LLMJudge", MagicMock()), \
         patch.object(_ai_rating_module, "AIRater", _NopAIRater), \
         patch("verdikt.api.deps.get_user_engine", return_value=mem_engine):
        resp = client.post(f"/api/projects/{project_id}/ai-rating/start")

    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_ai_rating_start_409_already_running(client, project_id, saved_profile, monkeypatch):
    """POST /start returns 409 when a job is already running for this project."""
    monkeypatch.setattr(_ai_rating_module, "_stop_flags", {project_id: []})
    monkeypatch.setattr(_ai_rating_module, "_status", {})

    resp = client.post(f"/api/projects/{project_id}/ai-rating/start")
    assert resp.status_code == 409


def test_ai_rating_start_503_no_profile(client, project_id, monkeypatch):
    """POST /start returns 503 when no profile has been crystallised."""
    monkeypatch.setattr(_ai_rating_module, "_stop_flags", {})

    resp = client.post(f"/api/projects/{project_id}/ai-rating/start")
    assert resp.status_code == 503


def test_ai_rating_stop_signals_flag(client, project_id, monkeypatch):
    """POST /stop appends to the stop flag and returns stopped."""
    stop_flag: list = []
    monkeypatch.setattr(_ai_rating_module, "_stop_flags", {project_id: stop_flag})
    monkeypatch.setattr(_ai_rating_module, "_status", {project_id: {"stopped_reason": None}})

    resp = client.post(f"/api/projects/{project_id}/ai-rating/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert stop_flag  # flag was signalled


def test_ai_rating_status_default(client, project_id, monkeypatch):
    """GET /status returns default zeros when no job has ever run."""
    monkeypatch.setattr(_ai_rating_module, "_status", {})

    resp = client.get(f"/api/projects/{project_id}/ai-rating/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["chunks_rated"] == 0
    assert data["batches_completed"] == 0
    assert data["last_batch_avg"] is None
    assert data["stopped_reason"] is None


def test_ai_rating_status_profile_stale(client, project_id, saved_profile, mem_engine, monkeypatch):
    """GET /status reports profile_stale when a newer profile version exists."""
    from verdikt.core.models import DimensionProfile, PreferenceProfile
    from verdikt.storage.sqlite import SQLiteProfileStore

    monkeypatch.setattr(_ai_rating_module, "_status", {
        project_id: {
            **_ai_rating_module._default_status(),
            "profile_version": saved_profile.version,
            "running": False,
        }
    })

    with Session(mem_engine) as s:
        p2 = PreferenceProfile(
            project_id=project_id,
            version=saved_profile.version + 1,
            dimensions=[DimensionProfile(name="Prose", description="d", summary="v2", typical_score=4.0)],
            overall_summary="Revised.",
            rating_count=10,
        )
        SQLiteProfileStore(s).save(p2)
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/ai-rating/status")
    assert resp.status_code == 200
    assert resp.json()["profile_stale"] is True


def test_next_chunk_confirm_ai_mode(client, project_id, ai_rated_chunk):
    """GET /ratings/next?mode=confirm_ai returns the highest-scored AI chunk with prefilled_scores."""
    chunk, rating = ai_rated_chunk

    resp = client.get(f"/api/projects/{project_id}/ratings/next?mode=confirm_ai")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunk"]["id"] == chunk.id
    assert data["prefilled_scores"] == rating.dimension_scores
    assert data["ai_rating_id"] == rating.id


def test_next_chunk_confirm_ai_mode_404_when_none(client, project_id):
    """GET /ratings/next?mode=confirm_ai returns 404 with no_ai_chunks when no AI ratings exist."""
    resp = client.get(f"/api/projects/{project_id}/ratings/next?mode=confirm_ai")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "no_ai_chunks"


def _insert_rated_chunk(session, project_id, mat_id, chunk_content, dim_scores, *, is_ai=False, explanations=None, position=0, project_seq=1):
    """Helper: insert MaterialItem + Chunk + Rating and return (chunk, rating)."""
    from datetime import datetime, timezone
    from verdikt.core.models import Chunk, Rating
    from verdikt.storage.orm import MaterialItemRow
    from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteRatingStore

    session.add(MaterialItemRow(
        id=mat_id,
        project_id=project_id,
        project_seq=project_seq,
        source_plugin="filedrop",
        source_path=f"/fake/{mat_id}.txt",
        content=chunk_content.encode() if isinstance(chunk_content, str) else chunk_content,
        content_is_bytes=False,
        domain="text",
        content_type="text/plain",
        pipeline_phase="clustered",
        ingested_at=datetime.now(timezone.utc),
    ))
    chunk = Chunk(
        project_id=project_id,
        material_item_id=mat_id,
        content=chunk_content,
        position=position,
        size=len(chunk_content.split()) if isinstance(chunk_content, str) else 1,
        cluster_id=0,
    )
    SQLiteChunkStore(session).save_many([chunk])
    rating = Rating(
        project_id=project_id,
        chunk_id=chunk.id,
        material_item_id=mat_id,
        dimension_scores=dim_scores,
        is_ai=is_ai,
        explanations=explanations or {},
        rated_at=datetime.now(timezone.utc),
    )
    SQLiteRatingStore(session).save(rating)
    return chunk, rating


def test_rated_chunks_returns_paginated_response(client, project_id, mem_engine):
    """GET /ratings/rated-chunks returns {total, items} shape with correct data."""
    with Session(mem_engine) as s:
        _insert_rated_chunk(s, project_id, "m_expl", "Some chunk content.", {"Prose": 4.0},
                            is_ai=True, explanations={"Prose": "Vivid and precise prose."})
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/ratings/rated-chunks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    entry = body["items"][0]
    assert entry["explanations"] == {"Prose": "Vivid and precise prose."}
    assert entry["avg_score"] == pytest.approx(4.0)
    assert entry["chunk_domain"] == "text"
    assert entry["chunk_content"] is None  # content omitted from list; fetched on demand via /works/chunk/{id}


def test_rated_chunks_counts_endpoint(client, project_id, mem_engine):
    """GET /ratings/counts returns {human, ai} breakdown."""
    with Session(mem_engine) as s:
        _insert_rated_chunk(s, project_id, "m_h", "human rated chunk", {"Prose": 3.0}, is_ai=False, project_seq=1)
        _insert_rated_chunk(s, project_id, "m_a1", "ai rated chunk 1", {"Prose": 4.0}, is_ai=True, project_seq=2)
        _insert_rated_chunk(s, project_id, "m_a2", "ai rated chunk 2", {"Prose": 2.0}, is_ai=True, project_seq=3)
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/ratings/counts")
    assert resp.status_code == 200
    counts = resp.json()
    assert counts["human"] == 1
    assert counts["ai"] == 2


def test_rated_chunks_deduplicates_human_over_ai(client, project_id, mem_engine):
    """When a chunk has both human and AI ratings, only the human rating appears and also_ai_rated=True."""
    from datetime import datetime, timezone
    from verdikt.core.models import Chunk, Rating
    from verdikt.storage.orm import MaterialItemRow
    from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteRatingStore

    with Session(mem_engine) as s:
        s.add(MaterialItemRow(
            id="m_dedup", project_id=project_id, project_seq=1, source_plugin="filedrop",
            source_path="/fake/dedup.txt", content=b"dedup chunk", content_is_bytes=False,
            domain="text", content_type="text/plain", pipeline_phase="clustered",
            ingested_at=datetime.now(timezone.utc),
        ))
        chunk = Chunk(project_id=project_id, material_item_id="m_dedup", content="dedup chunk", position=0, size=2, cluster_id=0)
        SQLiteChunkStore(s).save_many([chunk])
        SQLiteRatingStore(s).save(Rating(project_id=project_id, chunk_id=chunk.id, material_item_id="m_dedup",
                                         dimension_scores={"Prose": 4.0}, is_ai=False, rated_at=datetime.now(timezone.utc)))
        SQLiteRatingStore(s).save(Rating(project_id=project_id, chunk_id=chunk.id, material_item_id="m_dedup",
                                         dimension_scores={"Prose": 2.0}, is_ai=True, rated_at=datetime.now(timezone.utc)))
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/ratings/rated-chunks")
    body = resp.json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["is_ai"] is False
    assert entry["also_ai_rated"] is True
    assert entry["dimension_scores"]["Prose"] == pytest.approx(4.0)


def test_rated_chunks_pagination(client, project_id, mem_engine):
    """limit/offset parameters page through results correctly."""
    with Session(mem_engine) as s:
        for i in range(5):
            _insert_rated_chunk(s, project_id, f"m_pg{i}", f"chunk number {i}", {"Prose": float(i + 1)}, project_seq=i + 1)
        s.commit()

    resp_all = client.get(f"/api/projects/{project_id}/ratings/rated-chunks?limit=100&offset=0")
    assert resp_all.json()["total"] == 5

    resp_p1 = client.get(f"/api/projects/{project_id}/ratings/rated-chunks?limit=2&offset=0")
    resp_p2 = client.get(f"/api/projects/{project_id}/ratings/rated-chunks?limit=2&offset=2")
    assert len(resp_p1.json()["items"]) == 2
    assert len(resp_p2.json()["items"]) == 2

    ids_p1 = {e["rating_id"] for e in resp_p1.json()["items"]}
    ids_p2 = {e["rating_id"] for e in resp_p2.json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_rated_chunks_sort_by_avg_score(client, project_id, mem_engine):
    """sort_by=avg_score&sort_dir=desc returns highest-scored chunk first."""
    with Session(mem_engine) as s:
        _insert_rated_chunk(s, project_id, "m_lo", "low score chunk", {"Prose": 1.0}, project_seq=1)
        _insert_rated_chunk(s, project_id, "m_hi", "high score chunk", {"Prose": 5.0}, project_seq=2)
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/ratings/rated-chunks?sort_by=avg_score&sort_dir=desc")
    items = resp.json()["items"]
    assert items[0]["avg_score"] == pytest.approx(5.0)
    assert items[1]["avg_score"] == pytest.approx(1.0)


def test_rated_chunks_work_seq_filter(client, project_id, mem_engine):
    """work_seq filter returns only chunks from that work."""
    with Session(mem_engine) as s:
        _insert_rated_chunk(s, project_id, "m_w1", "work 1 chunk", {"Prose": 3.0}, project_seq=1)
        _insert_rated_chunk(s, project_id, "m_w2", "work 2 chunk", {"Prose": 4.0}, project_seq=2)
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/ratings/rated-chunks?work_seq=1")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["work_seq"] == 1


def test_chunk_content_endpoint(client, project_id, mem_engine):
    """GET /works/chunk/{chunk_id} returns content and domain for a single chunk."""
    with Session(mem_engine) as s:
        chunk, _ = _insert_rated_chunk(s, project_id, "m_cc", "Hello world content.", {"Prose": 3.0})
        chunk_id = chunk.id
        s.commit()

    resp = client.get(f"/api/projects/{project_id}/works/chunk/{chunk_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Hello world content."
    assert data["domain"] == "text"


def test_chunk_content_endpoint_404_wrong_project(client, project_id, mem_engine):
    """GET /works/chunk/{chunk_id} returns 404 when chunk belongs to a different project."""
    with Session(mem_engine) as s:
        chunk, _ = _insert_rated_chunk(s, project_id, "m_cc2", "Some text.", {"Prose": 3.0})
        chunk_id = chunk.id
        s.commit()

    resp = client.get(f"/api/projects/nonexistent-project/works/chunk/{chunk_id}")
    assert resp.status_code == 404


def test_update_rating_confirms_ai(client, project_id, ai_rated_chunk):
    """PUT /ratings/{id} with new scores clears is_ai (confirms the rating as human)."""
    chunk, rating = ai_rated_chunk

    resp = client.put(
        f"/api/projects/{project_id}/ratings/{rating.id}",
        json={"dimension_scores": {"Prose": 4.0}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dimension_scores"]["Prose"] == 4.0
    assert data["is_ai"] is False


# ── Model catalog endpoints ───────────────────────────────────────────────────

from sqlalchemy.pool import StaticPool as _StaticPool
from verdikt.api.deps import get_auth_session as _get_auth_session
from verdikt.storage.auth_orm import AuthBase, ModelCatalogRow


@pytest.fixture
def auth_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=_StaticPool,
    )
    AuthBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def catalog_client(mem_engine, auth_engine, tmp_path):
    app = create_app()

    def override_session():
        with Session(mem_engine) as s:
            yield s

    def override_auth_session():
        with Session(auth_engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: _MOCK_USER
    app.dependency_overrides[get_storage] = lambda: LocalStorageBackend(tmp_path / "files")
    app.dependency_overrides[_get_auth_session] = override_auth_session
    return TestClient(app)


def _seed_model(auth_engine, model_id: str, type_: str, domain: str,
                enabled: bool = True, is_default: bool = False) -> None:
    with Session(auth_engine) as s:
        s.add(ModelCatalogRow(
            id=model_id, source="ollama", type=type_, domain=domain,
            enabled=enabled, is_default=is_default,
            display_name=model_id, description="",
        ))
        s.commit()


def test_model_defaults_returns_per_domain(catalog_client, auth_engine):
    _seed_model(auth_engine, "llama3:8b", "llm", "text", is_default=True)
    _seed_model(auth_engine, "llava:7b", "llm", "image", is_default=True)

    resp = catalog_client.get("/api/models/defaults")
    assert resp.status_code == 200
    data = resp.json()["llm_by_domain"]
    assert data["text"] == "llama3:8b"
    assert data["image"] == "llava:7b"


def test_model_defaults_any_domain_fills_both(catalog_client, auth_engine):
    _seed_model(auth_engine, "universal:7b", "llm", "any", is_default=True)

    resp = catalog_client.get("/api/models/defaults")
    data = resp.json()["llm_by_domain"]
    assert data["text"] == "universal:7b"
    assert data["image"] == "universal:7b"


def test_model_defaults_disabled_model_not_returned(catalog_client, auth_engine):
    _seed_model(auth_engine, "disabled:7b", "llm", "text", enabled=False, is_default=True)

    resp = catalog_client.get("/api/models/defaults")
    assert resp.json()["llm_by_domain"]["text"] is None


def test_domain_availability_reflects_enabled_models(catalog_client, auth_engine):
    _seed_model(auth_engine, "text-llm:7b", "llm", "text")

    resp = catalog_client.get("/api/models/domain-availability")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] is True
    assert data["image"] is False


def test_domain_availability_any_domain_covers_all(catalog_client, auth_engine):
    _seed_model(auth_engine, "any-llm:7b", "llm", "any")

    resp = catalog_client.get("/api/models/domain-availability")
    data = resp.json()
    assert data["text"] is True
    assert data["image"] is True


def test_admin_set_default_clears_previous(catalog_client, auth_engine):
    _seed_model(auth_engine, "old:7b", "llm", "text", is_default=True)
    _seed_model(auth_engine, "new:7b", "llm", "text")

    resp = catalog_client.patch("/api/admin/models/new:7b", json={"is_default": True})
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    # old model must no longer be default
    with Session(auth_engine) as s:
        old = s.get(ModelCatalogRow, "old:7b")
        assert old.is_default is False


def test_admin_set_default_clears_any_domain_conflict(catalog_client, auth_engine):
    """Setting a text-domain model as default must clear an 'any'-domain default."""
    _seed_model(auth_engine, "universal:7b", "llm", "any", is_default=True)
    _seed_model(auth_engine, "text-only:7b", "llm", "text")

    catalog_client.patch("/api/admin/models/text-only:7b", json={"is_default": True})

    with Session(auth_engine) as s:
        universal = s.get(ModelCatalogRow, "universal:7b")
        assert universal.is_default is False


def test_admin_disable_model_clears_default(catalog_client, auth_engine):
    _seed_model(auth_engine, "m:7b", "llm", "text", is_default=True)

    catalog_client.patch("/api/admin/models/m:7b", json={"enabled": False})

    with Session(auth_engine) as s:
        row = s.get(ModelCatalogRow, "m:7b")
        assert row.is_default is False
