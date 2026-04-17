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
        row = self._to_row(project)
        self._s.add(row)
        self._s.flush()
        return project

    def get(self, project_id: str) -> Project | None:
        row = self._s.get(ProjectRow, project_id)
        return self._from_row(row) if row else None

    def list_all(self) -> list[Project]:
        rows = self._s.query(ProjectRow).all()
        return [self._from_row(r) for r in rows]

    @staticmethod
    def _to_row(p: Project) -> ProjectRow:
        return ProjectRow(
            id=p.id,
            name=p.name,
            description=p.description,
            domain=p.domain if isinstance(p.domain, str) else p.domain.value,
            rating_dimensions=json.dumps(
                [d.model_dump() for d in p.rating_dimensions]
            ),
            chunk_min_words=p.chunk_min_words,
            chunk_max_words=p.chunk_max_words,
            crystallisation_threshold=p.crystallisation_threshold,
            created_at=p.created_at,
        )

    @staticmethod
    def _from_row(r: ProjectRow) -> Project:
        dims = [RatingDimension(**d) for d in json.loads(r.rating_dimensions)]
        return Project(
            id=r.id,
            name=r.name,
            description=r.description,
            domain=r.domain,
            rating_dimensions=dims,
            chunk_min_words=r.chunk_min_words,
            chunk_max_words=r.chunk_max_words,
            crystallisation_threshold=r.crystallisation_threshold,
            created_at=r.created_at,
        )


class SQLiteMaterialStore(MaterialStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, item: MaterialItem) -> MaterialItem:
        row = self._to_row(item)
        self._s.add(row)
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
        q = self._s.query(MaterialItemRow).filter(
            MaterialItemRow.project_id == project_id
        )
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
            raw = item.content
            is_bytes = True
        else:
            raw = item.content.encode("utf-8")
            is_bytes = False
        return MaterialItemRow(
            id=item.id,
            project_id=item.project_id,
            source_plugin=item.source_plugin,
            url=item.url,
            work_title=item.work_title,
            author=item.author,
            work_id=item.work_id,
            chapter_position=item.chapter_position,
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
            chapter_position=r.chapter_position,
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
        rows = [self._to_row(c) for c in chunks]
        self._s.add_all(rows)
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
            update(ChunkRow)
            .where(ChunkRow.id == chunk_id)
            .values(cluster_id=cluster_id)
        )
        self._s.flush()

    @staticmethod
    def _to_row(c: Chunk) -> ChunkRow:
        return ChunkRow(
            id=c.id,
            material_item_id=c.material_item_id,
            project_id=c.project_id,
            text=c.text,
            position=c.position,
            word_count=c.word_count,
            cluster_id=c.cluster_id,
            embedding_model=c.embedding_model,
            created_at=c.created_at,
        )

    @staticmethod
    def _from_row(r: ChunkRow) -> Chunk:
        return Chunk(
            id=r.id,
            material_item_id=r.material_item_id,
            project_id=r.project_id,
            text=r.text,
            position=r.position,
            word_count=r.word_count,
            cluster_id=r.cluster_id,
            embedding_model=r.embedding_model,
            created_at=r.created_at,
        )
