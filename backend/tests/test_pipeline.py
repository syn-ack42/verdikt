from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.models import Chunk, Domain, MaterialItem, PipelinePhase
from verdikt.inference.base import EmbedderBase
from verdikt.pipeline.chunker import TextChunker
from verdikt.pipeline.runner import PipelineRunner
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
        for id_ in ids:
            self.upserted.remove(id_) if id_ in self.upserted else None


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_runner(session, vector_store=None, min_words=20, max_words=40):
    return PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=vector_store or MockVectorStore(),
        embedder=MockEmbedder(),
        chunker=TextChunker(min_words=min_words, max_words=max_words),
    )


def _ingest_item(session, text: str, project_id: str = "p1") -> MaterialItem:
    item = MaterialItem(
        project_id=project_id,
        source_plugin="test",
        content=text,
        domain=Domain.TEXT,
        content_type="text/plain",
    )
    SQLiteMaterialStore(session).save(item)
    session.flush()
    return item


def _long_text(words: int = 200) -> str:
    paras = []
    para_size = 30
    for i in range(0, words, para_size):
        paras.append(" ".join(f"word{j}" for j in range(i, min(i + para_size, words))))
    return "\n\n".join(paras)


# ── Unit tests (no infra marker) ──────────────────────────────────────────────

def test_chunk_phase_creates_chunks(mem_session):
    _ingest_item(mem_session, _long_text(200))
    runner = _make_runner(mem_session)
    result = runner._chunk("p1")
    assert result.items_processed > 0
    chunks = SQLiteChunkStore(mem_session).list_by_project("p1")
    assert len(chunks) > 0


def test_chunk_phase_updates_phase_to_chunked(mem_session):
    item = _ingest_item(mem_session, _long_text(200))
    _make_runner(mem_session)._chunk("p1")
    updated = SQLiteMaterialStore(mem_session).get(item.id)
    assert updated.pipeline_phase == "chunked"


def test_embed_phase_calls_vector_store_upsert(mem_session):
    _ingest_item(mem_session, _long_text(200))
    vector_store = MockVectorStore()
    runner = _make_runner(mem_session, vector_store=vector_store)
    runner._chunk("p1")
    mem_session.flush()
    runner._embed("p1")
    assert len(vector_store.upserted) > 0


def test_embed_phase_updates_phase_to_embedded(mem_session):
    item = _ingest_item(mem_session, _long_text(200))
    runner = _make_runner(mem_session)
    runner._chunk("p1")
    mem_session.flush()
    runner._embed("p1")
    updated = SQLiteMaterialStore(mem_session).get(item.id)
    assert updated.pipeline_phase == "embedded"


def test_cluster_phase_assigns_cluster_ids(mem_session):
    # Need enough chunks to cluster (≥ 2)
    for _ in range(3):
        _ingest_item(mem_session, _long_text(200))
    runner = _make_runner(mem_session)
    runner._chunk("p1")
    mem_session.flush()
    runner._embed("p1")
    mem_session.flush()
    runner._cluster("p1")
    mem_session.flush()
    chunks = SQLiteChunkStore(mem_session).list_by_project("p1")
    assert all(c.cluster_id is not None for c in chunks)


def test_cluster_phase_updates_phase_to_clustered(mem_session):
    item = _ingest_item(mem_session, _long_text(200))
    runner = _make_runner(mem_session)
    runner._chunk("p1")
    mem_session.flush()
    runner._embed("p1")
    mem_session.flush()
    runner._cluster("p1")
    updated = SQLiteMaterialStore(mem_session).get(item.id)
    assert updated.pipeline_phase == "clustered"


def test_run_returns_pipeline_result(mem_session):
    _ingest_item(mem_session, _long_text(200))
    result = _make_runner(mem_session).run("p1")
    assert len(result.phases) == 3
    assert [p.phase for p in result.phases] == ["chunk", "embed", "cluster"]


def test_idempotency_chunk_phase(mem_session):
    _ingest_item(mem_session, _long_text(200))
    runner = _make_runner(mem_session)
    runner._chunk("p1")
    mem_session.flush()
    count_after_first = len(SQLiteChunkStore(mem_session).list_by_project("p1"))

    # Second run: no INGESTED items remain, so no new chunks
    runner._chunk("p1")
    mem_session.flush()
    count_after_second = len(SQLiteChunkStore(mem_session).list_by_project("p1"))
    assert count_after_first == count_after_second


# ── Integration test (infra) ──────────────────────────────────────────────────

@pytest.mark.infra
def test_full_pipeline_end_to_end(tmp_path):
    import chromadb
    from verdikt.inference.embedder import SentenceTransformerEmbedder
    from verdikt.plugins.filedrop import FileDropPlugin
    from verdikt.storage.chroma import ChromaVectorStore

    for i in range(3):
        file = tmp_path / f"doc{i}.txt"
        file.write_text(
            "\n\n".join(
                " ".join(f"word{j}" for j in range(80))
                for _ in range(10)
            ),
            encoding="utf-8",
        )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        material_store = SQLiteMaterialStore(session)
        for item in FileDropPlugin(str(tmp_path)).fetch("p1"):
            material_store.save(item)
        session.flush()

        runner = PipelineRunner(
            material_store=material_store,
            chunk_store=SQLiteChunkStore(session),
            vector_store=ChromaVectorStore(chromadb.EphemeralClient(), "project_p1"),
            embedder=SentenceTransformerEmbedder(),
            chunker=TextChunker(min_words=100, max_words=150),
        )
        runner.run("p1")
        session.flush()

        items = material_store.list_by_project("p1")
        assert all(i.pipeline_phase == "clustered" for i in items)
        chunks = SQLiteChunkStore(session).list_by_project("p1")
        assert all(c.cluster_id is not None for c in chunks)
