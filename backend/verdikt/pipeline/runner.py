from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from math import isqrt
from typing import Any

from verdikt.core.models import Chunk, PipelinePhase
from verdikt.inference.base import EmbedderBase
from verdikt.pipeline.chunker import ChunkerBase
from verdikt.storage.base import ChunkStore, MaterialStore, VectorStore


@dataclass
class PhaseResult:
    phase: str
    items_processed: int = 0


@dataclass
class PipelineResult:
    project_id: str
    phases: list[PhaseResult] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return sum(p.items_processed for p in self.phases)


class PipelineRunner:
    """Sequential pipeline runner for Milestone 1.
    Prefect orchestration replaces this in Milestone 2.
    """

    def __init__(
        self,
        material_store: MaterialStore,
        chunk_store: ChunkStore,
        vector_store: VectorStore,
        embedder: EmbedderBase,
        chunker: ChunkerBase,
    ) -> None:
        self._materials = material_store
        self._chunks = chunk_store
        self._vectors = vector_store
        self._embedder = embedder
        self._chunker = chunker

    def run(self, project_id: str) -> PipelineResult:
        result = PipelineResult(project_id=project_id)
        for phase_name, stream_fn in [
            ("chunk", self._chunk_stream),
            ("embed", self._embed_stream),
            ("cluster", self._cluster_stream),
        ]:
            items_processed = 0
            for event in stream_fn(project_id):
                if event["type"] == "done":
                    items_processed = event["items_processed"]
            result.phases.append(PhaseResult(phase=phase_name, items_processed=items_processed))
        return result

    # ── Public sync wrappers (used by Prefect tasks in flows.py) ──────────────

    def _chunk(self, project_id: str) -> PhaseResult:
        result = None
        for event in self._chunk_stream(project_id):
            if event["type"] == "done":
                result = PhaseResult(phase="chunk", items_processed=event["items_processed"])
        return result  # type: ignore[return-value]

    def _embed(self, project_id: str) -> PhaseResult:
        result = None
        for event in self._embed_stream(project_id):
            if event["type"] == "done":
                result = PhaseResult(phase="embed", items_processed=event["items_processed"])
        return result  # type: ignore[return-value]

    def _cluster(self, project_id: str) -> PhaseResult:
        result = None
        for event in self._cluster_stream(project_id):
            if event["type"] == "done":
                result = PhaseResult(phase="cluster", items_processed=event["items_processed"])
        return result  # type: ignore[return-value]

    # ── Streaming generators (used by the SSE pipeline endpoint) ─────────────

    def _chunk_stream(self, project_id: str) -> Generator[dict[str, Any], None, None]:
        items = list(self._materials.list_by_project(project_id, phase=PipelinePhase.INGESTED))
        total = len(items)
        yield {"type": "start", "total": total}
        chunks_created = 0
        for i, item in enumerate(items):
            chunk_contents = self._chunker.chunk(item.content)
            chunks = [
                Chunk(
                    material_item_id=item.id,
                    project_id=project_id,
                    content=c,
                    position=j,
                    size=self._chunker.measure(c),
                )
                for j, c in enumerate(chunk_contents)
            ]
            if chunks:
                self._chunks.save_many(chunks)
                chunks_created += len(chunks)
            self._materials.update_phase(item.id, PipelinePhase.CHUNKED)
            yield {"type": "progress", "current": i + 1, "total": total}
        yield {"type": "done", "items_processed": chunks_created}

    def _embed_stream(self, project_id: str) -> Generator[dict[str, Any], None, None]:
        items = list(self._materials.list_by_project(project_id, phase=PipelinePhase.CHUNKED))
        all_chunks: list[Chunk] = []
        for item in items:
            all_chunks.extend(self._chunks.list_by_material(item.id))

        yield {"type": "start", "total": len(all_chunks)}

        if not all_chunks:
            yield {"type": "done", "items_processed": 0}
            return

        embeddings = self._embedder.embed([c.content for c in all_chunks])
        for chunk, embedding in zip(all_chunks, embeddings):
            self._vectors.upsert(
                item_id=chunk.id,
                embedding=embedding.tolist(),
                metadata={
                    "chunk_id": chunk.id,
                    "project_id": chunk.project_id,
                    "material_item_id": chunk.material_item_id,
                    "position": chunk.position,
                },
            )

        for item in items:
            self._materials.update_phase(item.id, PipelinePhase.EMBEDDED)

        yield {"type": "done", "items_processed": len(all_chunks)}

    def _cluster_stream(self, project_id: str) -> Generator[dict[str, Any], None, None]:
        from sklearn.cluster import KMeans

        items = list(self._materials.list_by_project(project_id, phase=PipelinePhase.EMBEDDED))
        all_chunks: list[Chunk] = []
        for item in items:
            all_chunks.extend(self._chunks.list_by_material(item.id))

        yield {"type": "start", "total": len(all_chunks)}

        if len(all_chunks) < 2:
            for item in items:
                self._materials.update_phase(item.id, PipelinePhase.CLUSTERED)
            yield {"type": "done", "items_processed": len(all_chunks)}
            return

        embeddings = self._embedder.embed([c.content for c in all_chunks])
        n_clusters = max(2, isqrt(len(all_chunks)))
        labels = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto").fit_predict(embeddings)

        for chunk, label in zip(all_chunks, labels):
            self._chunks.update_cluster(chunk.id, int(label))

        for item in items:
            self._materials.update_phase(item.id, PipelinePhase.CLUSTERED)

        yield {"type": "done", "items_processed": len(all_chunks)}
