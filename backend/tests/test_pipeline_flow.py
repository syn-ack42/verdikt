from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.models import Domain, MaterialItem, PipelinePhase
from verdikt.inference.base import EmbedderBase
from verdikt.pipeline.chunker import TextChunker
from verdikt.pipeline.flows import run_pipeline_flow
from verdikt.pipeline.runner import PipelineRunner
from verdikt.storage.base import VectorStore
from verdikt.storage.orm import Base
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore


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
        self._store: dict[str, list[float]] = {}

    def upsert(self, item_id: str, embedding: list[float], metadata: dict) -> None:
        self.upserted.append(item_id)
        self._store[item_id] = embedding

    def query(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        return []

    def delete_collection(self) -> None:
        self.upserted.clear()
        self._store.clear()

    def delete_items(self, ids: list[str]) -> None:
        self.upserted = [i for i in self.upserted if i not in ids]
        for id_ in ids:
            self._store.pop(id_, None)

    def get_all_embeddings(self) -> tuple[list[str], np.ndarray]:
        ids = list(self._store.keys())
        embs = np.array([self._store[i] for i in ids], dtype=np.float32) if ids else np.empty((0,), dtype=np.float32)
        return ids, embs


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


LONG_TEXT = " ".join(["word"] * 1200)


def _make_runner(session: Session) -> PipelineRunner:
    return PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=MockVectorStore(),
        embedder=MockEmbedder(),
        chunker=TextChunker(min_words=200, max_words=300),
    )


def test_flow_returns_pipeline_result_with_three_phases(mem_session: Session):
    proj_store = SQLiteProjectStore(mem_session)
    from verdikt.core.models import Project
    proj = Project(name="flow-test", domain=Domain.TEXT)
    proj_store.create(proj)

    mat_store = SQLiteMaterialStore(mem_session)
    item = MaterialItem(
        project_id=proj.id,
        source_plugin="test",
        content=LONG_TEXT,
        domain=Domain.TEXT,
        content_type="text/plain",
    )
    mat_store.save(item)

    runner = _make_runner(mem_session)
    result = run_pipeline_flow(project_id=proj.id, runner=runner)

    assert result.project_id == proj.id
    assert len(result.phases) == 3
    phase_names = [p.phase for p in result.phases]
    assert phase_names == ["chunk", "embed", "cluster"]
    assert result.total_processed > 0


def test_flow_all_items_reach_clustered_phase(mem_session: Session):
    from verdikt.core.models import Project
    proj = Project(name="flow-phase-test", domain=Domain.TEXT)
    SQLiteProjectStore(mem_session).create(proj)

    mat_store = SQLiteMaterialStore(mem_session)
    for i in range(3):
        mat_store.save(MaterialItem(
            project_id=proj.id,
            source_plugin="test",
            content=" ".join(["word"] * 900),
            domain=Domain.TEXT,
            content_type="text/plain",
        ))

    run_pipeline_flow(project_id=proj.id, runner=_make_runner(mem_session))

    items = mat_store.list_by_project(proj.id)
    for item in items:
        assert item.pipeline_phase == PipelinePhase.CLUSTERED.value
