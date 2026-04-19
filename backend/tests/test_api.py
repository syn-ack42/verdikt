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
