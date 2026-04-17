from __future__ import annotations

from dataclasses import dataclass, field
from math import isqrt

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
        for phase_fn in (self._chunk, self._embed, self._cluster):
            result.phases.append(phase_fn(project_id))
        return result

    def _chunk(self, project_id: str) -> PhaseResult:
        items = self._materials.list_by_project(project_id, phase=PipelinePhase.INGESTED)
        total = 0
        for item in items:
            chunk_contents = self._chunker.chunk(item.content)
            chunks = [
                Chunk(
                    material_item_id=item.id,
                    project_id=project_id,
                    content=c,
                    position=i,
                    size=self._chunker.measure(c),
                )
                for i, c in enumerate(chunk_contents)
            ]
            if chunks:
                self._chunks.save_many(chunks)
                total += len(chunks)
            self._materials.update_phase(item.id, PipelinePhase.CHUNKED)
        return PhaseResult(phase="chunk", items_processed=total)

    def _embed(self, project_id: str) -> PhaseResult:
        items = self._materials.list_by_project(project_id, phase=PipelinePhase.CHUNKED)
        all_chunks: list[Chunk] = []
        for item in items:
            all_chunks.extend(self._chunks.list_by_material(item.id))

        if not all_chunks:
            return PhaseResult(phase="embed", items_processed=0)

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

        return PhaseResult(phase="embed", items_processed=len(all_chunks))

    def _cluster(self, project_id: str) -> PhaseResult:
        from sklearn.cluster import KMeans

        items = self._materials.list_by_project(project_id, phase=PipelinePhase.EMBEDDED)
        all_chunks: list[Chunk] = []
        for item in items:
            all_chunks.extend(self._chunks.list_by_material(item.id))

        if len(all_chunks) < 2:
            for item in items:
                self._materials.update_phase(item.id, PipelinePhase.CLUSTERED)
            return PhaseResult(phase="cluster", items_processed=len(all_chunks))

        # Re-embed rather than loading from ChromaDB — ordering from bulk get() is
        # fragile; at M1 scale re-embedding is fast. TODO(M5): load from vector store.
        embeddings = self._embedder.embed([c.content for c in all_chunks])
        n_clusters = max(2, isqrt(len(all_chunks)))
        labels = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto").fit_predict(embeddings)

        for chunk, label in zip(all_chunks, labels):
            self._chunks.update_cluster(chunk.id, int(label))

        for item in items:
            self._materials.update_phase(item.id, PipelinePhase.CLUSTERED)

        return PhaseResult(phase="cluster", items_processed=len(all_chunks))
