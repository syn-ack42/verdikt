from __future__ import annotations

import json

from sqlalchemy import update
from sqlalchemy.orm import Session

from verdikt.core.models import Chunk, MaterialItem, PipelinePhase, Project, RatingDimension
from verdikt.storage.base import ChunkStore, MaterialStore, ProjectStore
from verdikt.storage.orm import ChunkRow, MaterialItemRow, ProjectRow


class SQLiteProjectStore(ProjectStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, project: Project) -> Project:
        self._s.add(self._to_row(project))
        self._s.flush()
        return project

    def get(self, project_id: str) -> Project | None:
        row = self._s.get(ProjectRow, project_id)
        return self._from_row(row) if row else None

    def list_all(self) -> list[Project]:
        return [self._from_row(r) for r in self._s.query(ProjectRow).all()]

    @staticmethod
    def _to_row(p: Project) -> ProjectRow:
        return ProjectRow(
            id=p.id,
            name=p.name,
            description=p.description,
            domain=p.domain if isinstance(p.domain, str) else p.domain.value,
            rating_dimensions=json.dumps([d.model_dump() for d in p.rating_dimensions]),
            chunk_min_size=p.chunk_min_size,
            chunk_max_size=p.chunk_max_size,
            crystallisation_threshold=p.crystallisation_threshold,
            created_at=p.created_at,
        )

    @staticmethod
    def _from_row(r: ProjectRow) -> Project:
        return Project(
            id=r.id,
            name=r.name,
            description=r.description,
            domain=r.domain,
            rating_dimensions=[RatingDimension(**d) for d in json.loads(r.rating_dimensions)],
            chunk_min_size=r.chunk_min_size,
            chunk_max_size=r.chunk_max_size,
            crystallisation_threshold=r.crystallisation_threshold,
            created_at=r.created_at,
        )


class SQLiteMaterialStore(MaterialStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, item: MaterialItem) -> MaterialItem:
        self._s.add(self._to_row(item))
        self._s.flush()
        return item

    def get(self, item_id: str) -> MaterialItem | None:
        row = self._s.get(MaterialItemRow, item_id)
        return self._from_row(row) if row else None

    def list_by_project(
        self,
        project_id: str,
        phase: PipelinePhase | None = None,
    ) -> list[MaterialItem]:
        q = self._s.query(MaterialItemRow).filter(MaterialItemRow.project_id == project_id)
        if phase is not None:
            phase_val = phase.value if hasattr(phase, "value") else phase
            q = q.filter(MaterialItemRow.pipeline_phase == phase_val)
        return [self._from_row(r) for r in q.all()]

    def update_phase(self, item_id: str, phase: PipelinePhase) -> None:
        phase_val = phase.value if hasattr(phase, "value") else phase
        self._s.execute(
            update(MaterialItemRow)
            .where(MaterialItemRow.id == item_id)
            .values(pipeline_phase=phase_val)
        )
        self._s.flush()

    @staticmethod
    def _to_row(item: MaterialItem) -> MaterialItemRow:
        if isinstance(item.content, bytes):
            raw, is_bytes = item.content, True
        else:
            raw, is_bytes = item.content.encode("utf-8"), False
        return MaterialItemRow(
            id=item.id,
            project_id=item.project_id,
            source_plugin=item.source_plugin,
            url=item.url,
            work_title=item.work_title,
            author=item.author,
            work_id=item.work_id,
            sequence_position=item.sequence_position,
            content=raw,
            content_is_bytes=is_bytes,
            domain=item.domain if isinstance(item.domain, str) else item.domain.value,
            content_type=item.content_type if isinstance(item.content_type, str) else item.content_type.value,
            pipeline_phase=item.pipeline_phase if isinstance(item.pipeline_phase, str) else item.pipeline_phase.value,
            ingested_at=item.ingested_at,
        )

    @staticmethod
    def _from_row(r: MaterialItemRow) -> MaterialItem:
        content: bytes | str = r.content if r.content_is_bytes else r.content.decode("utf-8")
        return MaterialItem(
            id=r.id,
            project_id=r.project_id,
            source_plugin=r.source_plugin,
            url=r.url,
            work_title=r.work_title,
            author=r.author,
            work_id=r.work_id,
            sequence_position=r.sequence_position,
            content=content,
            domain=r.domain,
            content_type=r.content_type,
            pipeline_phase=r.pipeline_phase,
            ingested_at=r.ingested_at,
        )


class SQLiteChunkStore(ChunkStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save_many(self, chunks: list[Chunk]) -> list[Chunk]:
        self._s.add_all([self._to_row(c) for c in chunks])
        self._s.flush()
        return chunks

    def list_by_material(self, material_item_id: str) -> list[Chunk]:
        rows = (
            self._s.query(ChunkRow)
            .filter(ChunkRow.material_item_id == material_item_id)
            .order_by(ChunkRow.position)
            .all()
        )
        return [self._from_row(r) for r in rows]

    def list_by_project(self, project_id: str) -> list[Chunk]:
        rows = (
            self._s.query(ChunkRow)
            .filter(ChunkRow.project_id == project_id)
            .order_by(ChunkRow.material_item_id, ChunkRow.position)
            .all()
        )
        return [self._from_row(r) for r in rows]

    def update_cluster(self, chunk_id: str, cluster_id: int) -> None:
        self._s.execute(
            update(ChunkRow).where(ChunkRow.id == chunk_id).values(cluster_id=cluster_id)
        )
        self._s.flush()

    @staticmethod
    def _to_row(c: Chunk) -> ChunkRow:
        if isinstance(c.content, bytes):
            raw, is_str = c.content, False
        else:
            raw, is_str = c.content.encode("utf-8"), True
        return ChunkRow(
            id=c.id,
            material_item_id=c.material_item_id,
            project_id=c.project_id,
            content=raw,
            content_is_str=is_str,
            position=c.position,
            size=c.size,
            cluster_id=c.cluster_id,
            embedding_model=c.embedding_model,
            created_at=c.created_at,
        )

    @staticmethod
    def _from_row(r: ChunkRow) -> Chunk:
        content: str | bytes = r.content.decode("utf-8") if r.content_is_str else r.content
        return Chunk(
            id=r.id,
            material_item_id=r.material_item_id,
            project_id=r.project_id,
            content=content,
            position=r.position,
            size=r.size,
            cluster_id=r.cluster_id,
            embedding_model=r.embedding_model,
            created_at=r.created_at,
        )
