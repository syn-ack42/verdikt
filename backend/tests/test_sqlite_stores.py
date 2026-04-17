import json

import pytest

from verdikt.core.models import Chunk, Domain, MaterialItem, PipelinePhase, Project, RatingDimension
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore


# ── ProjectStore ────────────────────────────────────────────────────────────

def test_project_create_and_get(session):
    store = SQLiteProjectStore(session)
    proj = Project(name="Fantasy", domain=Domain.TEXT)
    store.create(proj)
    session.flush()

    result = store.get(proj.id)
    assert result is not None
    assert result.id == proj.id
    assert result.name == "Fantasy"


def test_project_get_nonexistent_returns_none(session):
    assert SQLiteProjectStore(session).get("no-such-id") is None


def test_project_list_all_empty(session):
    assert SQLiteProjectStore(session).list_all() == []


def test_project_list_all_returns_all(session):
    store = SQLiteProjectStore(session)
    store.create(Project(name="A"))
    store.create(Project(name="B"))
    session.flush()
    assert len(store.list_all()) == 2


def test_project_rating_dimensions_round_trip(session):
    dims = [
        RatingDimension(name="prose", description="Quality", weight=1.5),
        RatingDimension(name="pacing", description="Speed", weight=0.8),
    ]
    proj = Project(name="test", rating_dimensions=dims)
    SQLiteProjectStore(session).create(proj)
    session.flush()

    result = SQLiteProjectStore(session).get(proj.id)
    assert len(result.rating_dimensions) == 2
    assert result.rating_dimensions[0].name == "prose"
    assert result.rating_dimensions[0].weight == 1.5


# ── MaterialStore ────────────────────────────────────────────────────────────

def _make_item(project_id: str = "p1", content: str | bytes = "text content") -> MaterialItem:
    return MaterialItem(
        project_id=project_id,
        source_plugin="filedrop",
        content=content,
        domain=Domain.TEXT,
        content_type="text/plain",
    )


def test_material_save_and_get(session):
    store = SQLiteMaterialStore(session)
    item = _make_item()
    store.save(item)
    session.flush()

    result = store.get(item.id)
    assert result is not None
    assert result.id == item.id
    assert result.project_id == "p1"


def test_material_get_nonexistent_returns_none(session):
    assert SQLiteMaterialStore(session).get("missing") is None


def test_material_list_by_project_filters(session):
    store = SQLiteMaterialStore(session)
    store.save(_make_item(project_id="p1"))
    store.save(_make_item(project_id="p2"))
    session.flush()

    p1_items = store.list_by_project("p1")
    assert len(p1_items) == 1
    assert p1_items[0].project_id == "p1"


def test_material_list_by_project_phase_filter(session):
    store = SQLiteMaterialStore(session)
    item = _make_item()
    store.save(item)
    store.update_phase(item.id, PipelinePhase.CHUNKED)
    session.flush()

    ingested = store.list_by_project("p1", phase=PipelinePhase.INGESTED)
    chunked = store.list_by_project("p1", phase=PipelinePhase.CHUNKED)
    assert len(ingested) == 0
    assert len(chunked) == 1


def test_material_update_phase(session):
    store = SQLiteMaterialStore(session)
    item = _make_item()
    store.save(item)
    store.update_phase(item.id, PipelinePhase.EMBEDDED)
    session.flush()

    result = store.get(item.id)
    assert result.pipeline_phase == "embedded"


def test_material_content_str_round_trip(session):
    store = SQLiteMaterialStore(session)
    item = _make_item(content="hello unicode ñ")
    store.save(item)
    session.flush()

    result = store.get(item.id)
    assert isinstance(result.content, str)
    assert result.content == "hello unicode ñ"


def test_material_content_bytes_round_trip(session):
    store = SQLiteMaterialStore(session)
    item = _make_item(content=b"\x00\x01\x02binary")
    store.save(item)
    session.flush()

    result = store.get(item.id)
    assert isinstance(result.content, bytes)
    assert result.content == b"\x00\x01\x02binary"


# ── ChunkStore ───────────────────────────────────────────────────────────────

def _make_chunk(material_item_id: str = "m1", project_id: str = "p1", position: int = 0) -> Chunk:
    return Chunk(
        material_item_id=material_item_id,
        project_id=project_id,
        text="chunk text " * 10,
        position=position,
        word_count=20,
    )


def test_chunk_save_many_and_list_by_material(session):
    store = SQLiteChunkStore(session)
    chunks = [_make_chunk(position=i) for i in range(3)]
    store.save_many(chunks)
    session.flush()

    result = store.list_by_material("m1")
    assert len(result) == 3
    assert [r.position for r in result] == [0, 1, 2]


def test_chunk_list_by_project(session):
    store = SQLiteChunkStore(session)
    store.save_many([_make_chunk(project_id="p1"), _make_chunk(project_id="p2")])
    session.flush()

    assert len(store.list_by_project("p1")) == 1
    assert len(store.list_by_project("p2")) == 1


def test_chunk_update_cluster(session):
    store = SQLiteChunkStore(session)
    chunk = _make_chunk()
    store.save_many([chunk])
    session.flush()

    store.update_cluster(chunk.id, 3)
    session.flush()

    result = store.list_by_material("m1")[0]
    assert result.cluster_id == 3


def test_chunk_save_many_returns_correct_count(session):
    chunks = [_make_chunk(position=i) for i in range(5)]
    result = SQLiteChunkStore(session).save_many(chunks)
    assert len(result) == 5
