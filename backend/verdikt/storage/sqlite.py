from __future__ import annotations

import json

from sqlalchemy import delete as sql_delete, func, select, update
from sqlalchemy.orm import Session

from verdikt.core.models import (
    Chunk, DimensionProfile, MaterialItem, PipelinePhase,
    PluginConfig, PreferenceProfile, Project, Rating, RatingDimension,
)
from verdikt.storage.base import ChunkStore, MaterialStore, PluginConfigStore, ProfileStore, ProjectStore, RatingStore
from verdikt.storage.orm import ChunkRow, MaterialItemRow, PluginConfigRow, PreferenceProfileRow, ProjectRow, RatingRow


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

    def delete(self, project_id: str) -> None:
        self._s.execute(sql_delete(ProjectRow).where(ProjectRow.id == project_id))
        self._s.flush()

    def get_by_name(self, name: str) -> list[Project]:
        rows = self._s.execute(
            select(ProjectRow).where(ProjectRow.name == name)
        ).scalars().all()
        return [self._from_row(r) for r in rows]

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
            min_profile_confidence=p.min_profile_confidence,
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
            min_profile_confidence=getattr(r, 'min_profile_confidence', 0.9) or 0.9,
            created_at=r.created_at,
        )


class SQLiteMaterialStore(MaterialStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, item: MaterialItem) -> MaterialItem:
        item.project_seq = self._next_seq(item.project_id)
        self._s.add(self._to_row(item))
        self._s.flush()
        return item

    def _next_seq(self, project_id: str) -> int:
        result = self._s.execute(
            select(func.max(MaterialItemRow.project_seq))
            .where(MaterialItemRow.project_id == project_id)
        ).scalar()
        return (result or 0) + 1

    def get(self, item_id: str) -> MaterialItem | None:
        row = self._s.get(MaterialItemRow, item_id)
        return self._from_row(row) if row else None

    def list_by_project(
        self,
        project_id: str,
        phase: PipelinePhase | None = None,
    ) -> list[MaterialItem]:
        q = (
            self._s.query(MaterialItemRow)
            .filter(MaterialItemRow.project_id == project_id)
            .order_by(MaterialItemRow.project_seq)
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

    def get_by_seq(self, project_id: str, seq: int) -> MaterialItem | None:
        row = self._s.execute(
            select(MaterialItemRow).where(
                MaterialItemRow.project_id == project_id,
                MaterialItemRow.project_seq == seq,
            )
        ).scalar_one_or_none()
        return self._from_row(row) if row else None

    def get_by_source_path(self, project_id: str, source_path: str) -> MaterialItem | None:
        row = self._s.execute(
            select(MaterialItemRow).where(
                MaterialItemRow.project_id == project_id,
                MaterialItemRow.source_path == source_path,
            )
        ).scalar_one_or_none()
        return self._from_row(row) if row else None

    def delete(self, item_id: str) -> None:
        self._s.execute(sql_delete(MaterialItemRow).where(MaterialItemRow.id == item_id))
        self._s.flush()

    def list_by_source_plugin(self, project_id: str, source_plugin: str) -> list[MaterialItem]:
        rows = self._s.execute(
            select(MaterialItemRow).where(
                MaterialItemRow.project_id == project_id,
                MaterialItemRow.source_plugin == source_plugin,
            ).order_by(MaterialItemRow.project_seq)
        ).scalars().all()
        return [self._from_row(r) for r in rows]

    def get_by_source(self, project_id: str, source_plugin: str, source_path: str) -> MaterialItem | None:
        row = self._s.execute(
            select(MaterialItemRow).where(
                MaterialItemRow.project_id == project_id,
                MaterialItemRow.source_plugin == source_plugin,
                MaterialItemRow.source_path == source_path,
            )
        ).scalar_one_or_none()
        return self._from_row(row) if row else None

    def update_plugin_metadata(self, item_id: str, plugin_metadata: dict) -> None:
        self._s.execute(
            update(MaterialItemRow)
            .where(MaterialItemRow.id == item_id)
            .values(plugin_metadata_json=json.dumps(plugin_metadata))
        )
        self._s.flush()

    def update_content(self, item_id: str, content: bytes | str, content_hash: str | None, plugin_metadata: dict | None = None) -> None:
        if isinstance(content, bytes):
            raw, is_bytes = content, True
        else:
            raw, is_bytes = content.encode("utf-8"), False
        values: dict = {
            "content": raw,
            "content_is_bytes": is_bytes,
            "content_hash": content_hash,
            "pipeline_phase": PipelinePhase.INGESTED.value,
        }
        if plugin_metadata is not None:
            values["plugin_metadata_json"] = json.dumps(plugin_metadata)
        self._s.execute(update(MaterialItemRow).where(MaterialItemRow.id == item_id).values(**values))
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
            source_path=item.source_path,
            project_seq=item.project_seq,
            content_hash=item.content_hash,
            url=item.url,
            work_title=item.work_title,
            author=item.author,
            sequence_position=item.sequence_position,
            content=raw,
            content_is_bytes=is_bytes,
            domain=item.domain if isinstance(item.domain, str) else item.domain.value,
            content_type=item.content_type if isinstance(item.content_type, str) else item.content_type.value,
            pipeline_phase=item.pipeline_phase if isinstance(item.pipeline_phase, str) else item.pipeline_phase.value,
            ingested_at=item.ingested_at,
            plugin_metadata_json=json.dumps(item.plugin_metadata),
        )

    @staticmethod
    def _from_row(r: MaterialItemRow) -> MaterialItem:
        content: bytes | str = r.content if r.content_is_bytes else r.content.decode("utf-8")
        return MaterialItem(
            id=r.id,
            project_id=r.project_id,
            source_plugin=r.source_plugin,
            source_path=r.source_path,
            project_seq=r.project_seq,
            content_hash=r.content_hash,
            url=r.url,
            work_title=r.work_title,
            author=r.author,
            sequence_position=r.sequence_position,
            content=content,
            domain=r.domain,
            content_type=r.content_type,
            pipeline_phase=r.pipeline_phase,
            ingested_at=r.ingested_at,
            plugin_metadata=json.loads(r.plugin_metadata_json or "{}"),
        )


class SQLiteChunkStore(ChunkStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, chunk_id: str) -> Chunk | None:
        row = self._s.get(ChunkRow, chunk_id)
        return self._from_row(row) if row else None

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

    def delete_by_material(self, material_item_id: str) -> None:
        self._s.execute(sql_delete(ChunkRow).where(ChunkRow.material_item_id == material_item_id))
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


class SQLiteRatingStore(RatingStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, rating: Rating) -> Rating:
        self._s.add(self._to_row(rating))
        self._s.flush()
        return rating

    def get(self, rating_id: str) -> Rating | None:
        row = self._s.get(RatingRow, rating_id)
        return self._from_row(row) if row else None

    def list_by_project(self, project_id: str) -> list[Rating]:
        rows = self._s.execute(
            select(RatingRow).where(RatingRow.project_id == project_id)
        ).scalars().all()
        return [self._from_row(r) for r in rows]

    def list_by_chunk(self, chunk_id: str) -> list[Rating]:
        rows = self._s.execute(
            select(RatingRow).where(RatingRow.chunk_id == chunk_id)
        ).scalars().all()
        return [self._from_row(r) for r in rows]

    def count_by_project(self, project_id: str) -> int:
        return self._s.execute(
            select(func.count()).select_from(RatingRow).where(RatingRow.project_id == project_id)
        ).scalar() or 0

    def count_skipped(self, project_id: str) -> int:
        return self._s.execute(
            select(func.count()).select_from(RatingRow).where(
                RatingRow.project_id == project_id,
                RatingRow.skipped == True,  # noqa: E712
            )
        ).scalar() or 0

    def update_scores(self, rating_id: str, dimension_scores: dict) -> None:
        self._s.execute(
            update(RatingRow)
            .where(RatingRow.id == rating_id)
            .values(dimension_scores=json.dumps(dimension_scores), skipped=False, skip_reason=None, is_ai=False)
        )
        self._s.flush()

    def update_ai_scores(self, rating_id: str, dimension_scores: dict) -> None:
        """Update scores on an existing AI rating (re-scoring with new profile)."""
        from datetime import datetime, timezone
        self._s.execute(
            update(RatingRow)
            .where(RatingRow.id == rating_id)
            .values(
                dimension_scores=json.dumps(dimension_scores),
                rated_at=datetime.now(timezone.utc),
            )
        )
        self._s.flush()

    def delete_by_material(self, material_item_id: str) -> None:
        self._s.execute(
            sql_delete(RatingRow).where(RatingRow.material_item_id == material_item_id)
        )
        self._s.flush()

    def list_unconfirmed_ai(self, project_id: str) -> list[Rating]:
        rows = self._s.execute(
            select(RatingRow).where(
                RatingRow.project_id == project_id,
                RatingRow.is_ai == True,  # noqa: E712
                RatingRow.skipped == False,  # noqa: E712
            )
        ).scalars().all()
        # Sort by avg dimension score descending
        def _avg(r: RatingRow) -> float:
            scores = json.loads(r.dimension_scores)
            return sum(scores.values()) / len(scores) if scores else 0.0
        return [self._from_row(r) for r in sorted(rows, key=_avg, reverse=True)]

    def get_all_rated_chunk_ids(self, project_id: str) -> set[str]:
        rows = self._s.execute(
            select(RatingRow.chunk_id).where(RatingRow.project_id == project_id)
        ).scalars().all()
        return set(rows)

    def count_by_type(self, project_id: str) -> dict:
        from sqlalchemy import case
        rows = self._s.execute(
            select(RatingRow.is_ai, func.count())
            .where(RatingRow.project_id == project_id, RatingRow.skipped == False)  # noqa: E712
            .group_by(RatingRow.is_ai)
        ).all()
        result = {"human": 0, "ai": 0}
        for is_ai, count in rows:
            if is_ai:
                result["ai"] = count
            else:
                result["human"] = count
        return result

    @staticmethod
    def _to_row(r: Rating) -> RatingRow:
        return RatingRow(
            id=r.id,
            project_id=r.project_id,
            chunk_id=r.chunk_id,
            material_item_id=r.material_item_id,
            dimension_scores=json.dumps(r.dimension_scores),
            skipped=r.skipped,
            skip_reason=r.skip_reason,
            is_ai=r.is_ai,
            explanations=json.dumps(r.explanations) if r.explanations else None,
            rated_at=r.rated_at,
        )

    @staticmethod
    def _from_row(r: RatingRow) -> Rating:
        return Rating(
            id=r.id,
            project_id=r.project_id,
            chunk_id=r.chunk_id,
            material_item_id=r.material_item_id,
            dimension_scores=json.loads(r.dimension_scores),
            skipped=r.skipped,
            skip_reason=r.skip_reason,
            is_ai=r.is_ai,
            explanations=json.loads(r.explanations) if r.explanations else {},
            rated_at=r.rated_at,
        )


class SQLiteProfileStore(ProfileStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, profile: PreferenceProfile) -> PreferenceProfile:
        self._s.add(self._to_row(profile))
        self._s.flush()
        return profile

    def get_latest(self, project_id: str) -> PreferenceProfile | None:
        row = self._s.execute(
            select(PreferenceProfileRow)
            .where(PreferenceProfileRow.project_id == project_id)
            .order_by(PreferenceProfileRow.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        return self._from_row(row) if row else None

    def list_versions(self, project_id: str) -> list[PreferenceProfile]:
        rows = self._s.execute(
            select(PreferenceProfileRow)
            .where(PreferenceProfileRow.project_id == project_id)
            .order_by(PreferenceProfileRow.version.desc())
        ).scalars().all()
        return [self._from_row(r) for r in rows]

    def update(self, profile: PreferenceProfile) -> PreferenceProfile:
        self._s.execute(
            update(PreferenceProfileRow)
            .where(PreferenceProfileRow.id == profile.id)
            .values(
                dimensions_json=json.dumps([d.model_dump() for d in profile.dimensions]),
                overall_summary=profile.overall_summary,
            )
        )
        self._s.flush()
        return profile

    def increment_confidence(self, project_id: str, agreement_score: float) -> None:
        """Accumulate one AI-confirmation agreement score onto the latest profile version."""
        row = self._s.execute(
            select(PreferenceProfileRow)
            .where(PreferenceProfileRow.project_id == project_id)
            .order_by(PreferenceProfileRow.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return
        row.confirmed_count = (row.confirmed_count or 0) + 1
        row.score_sum = (row.score_sum or 0.0) + agreement_score
        self._s.flush()

    @staticmethod
    def _to_row(p: PreferenceProfile) -> PreferenceProfileRow:
        return PreferenceProfileRow(
            id=p.id,
            project_id=p.project_id,
            version=p.version,
            dimensions_json=json.dumps([d.model_dump() for d in p.dimensions]),
            overall_summary=p.overall_summary,
            rating_count=p.rating_count,
            confirmed_count=p.confirmed_count,
            score_sum=p.score_sum,
            created_at=p.created_at,
        )

    @staticmethod
    def _from_row(r: PreferenceProfileRow) -> PreferenceProfile:
        return PreferenceProfile(
            id=r.id,
            project_id=r.project_id,
            version=r.version,
            dimensions=[DimensionProfile(**d) for d in json.loads(r.dimensions_json)],
            overall_summary=r.overall_summary,
            rating_count=r.rating_count,
            confirmed_count=getattr(r, 'confirmed_count', 0) or 0,
            score_sum=getattr(r, 'score_sum', 0.0) or 0.0,
            created_at=r.created_at,
        )


class SQLitePluginConfigStore(PluginConfigStore):
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, cfg: PluginConfig) -> PluginConfig:
        existing = self._s.execute(
            select(PluginConfigRow)
            .where(PluginConfigRow.project_id == cfg.project_id)
            .where(PluginConfigRow.plugin_name == cfg.plugin_name)
        ).scalar_one_or_none()
        if existing:
            existing.config_json = json.dumps(cfg.config)
            existing.updated_at = cfg.updated_at
            cfg = PluginConfig(
                id=existing.id,
                project_id=existing.project_id,
                plugin_name=existing.plugin_name,
                config=cfg.config,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )
        else:
            self._s.add(PluginConfigRow(
                id=cfg.id,
                project_id=cfg.project_id,
                plugin_name=cfg.plugin_name,
                config_json=json.dumps(cfg.config),
                created_at=cfg.created_at,
                updated_at=cfg.updated_at,
            ))
        self._s.flush()
        return cfg

    def get(self, project_id: str, plugin_name: str) -> PluginConfig | None:
        row = self._s.execute(
            select(PluginConfigRow)
            .where(PluginConfigRow.project_id == project_id)
            .where(PluginConfigRow.plugin_name == plugin_name)
        ).scalar_one_or_none()
        return self._from_row(row) if row else None

    def list_by_project(self, project_id: str) -> list[PluginConfig]:
        rows = self._s.execute(
            select(PluginConfigRow).where(PluginConfigRow.project_id == project_id)
        ).scalars().all()
        return [self._from_row(r) for r in rows]

    def delete(self, project_id: str, plugin_name: str) -> None:
        self._s.execute(
            sql_delete(PluginConfigRow)
            .where(PluginConfigRow.project_id == project_id)
            .where(PluginConfigRow.plugin_name == plugin_name)
        )
        self._s.flush()

    @staticmethod
    def _from_row(r: PluginConfigRow) -> PluginConfig:
        return PluginConfig(
            id=r.id,
            project_id=r.project_id,
            plugin_name=r.plugin_name,
            config=json.loads(r.config_json),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
