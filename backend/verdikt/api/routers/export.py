from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_current_user, get_session
from verdikt.core.models import (
    Domain,
    MaterialItem,
    PipelinePhase,
    PluginConfig,
    PreferenceProfile,
    Project,
    Rating,
    RatingDimension,
)
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.sqlite import (
    SQLiteChunkStore,
    SQLiteMaterialStore,
    SQLitePluginConfigStore,
    SQLiteProfileStore,
    SQLiteProjectStore,
    SQLiteRatingStore,
)

router = APIRouter(prefix="/api/projects", tags=["export"])


@router.get("/{project_id}/export")
def export_project(
    project_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
) -> StreamingResponse:
    store = SQLiteProjectStore(session)
    proj = store.get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")

    mat_store = SQLiteMaterialStore(session)
    rating_store = SQLiteRatingStore(session)
    profile_store = SQLiteProfileStore(session)
    plugin_store = SQLitePluginConfigStore(session)

    materials = mat_store.list_by_project(project_id)
    ratings = rating_store.list_by_project(project_id)
    profiles = profile_store.list_versions(project_id)
    plugin_configs = plugin_store.list_by_project(project_id)

    payload = {
        "version": 1,
        "project": {
            "id": proj.id,
            "name": proj.name,
            "description": proj.description,
            "domain": proj.domain,
            "rating_dimensions": [d.model_dump() for d in proj.rating_dimensions],
            "chunk_min_size": proj.chunk_min_size,
            "chunk_max_size": proj.chunk_max_size,
            "crystallisation_threshold": proj.crystallisation_threshold,
            "created_at": proj.created_at.isoformat(),
        },
        "materials": [
            {
                "id": m.id,
                "source_plugin": m.source_plugin,
                "source_path": m.source_path,
                "work_title": m.work_title,
                "author": m.author,
                "url": m.url,
                "domain": m.domain,
                "content_type": m.content_type,
                "pipeline_phase": m.pipeline_phase,
                "content_hash": m.content_hash,
                "ingested_at": m.ingested_at.isoformat(),
                "plugin_metadata": m.plugin_metadata,
            }
            for m in materials
        ],
        "ratings": [
            {
                "id": r.id,
                "chunk_id": r.chunk_id,
                "material_item_id": r.material_item_id,
                "dimension_scores": r.dimension_scores,
                "skipped": r.skipped,
                "skip_reason": r.skip_reason,
                "is_ai": r.is_ai,
                "rated_at": r.rated_at.isoformat(),
            }
            for r in ratings
        ],
        "profiles": [
            {
                "id": p.id,
                "version": p.version,
                "dimensions": [d.model_dump() for d in p.dimensions],
                "overall_summary": p.overall_summary,
                "rating_count": p.rating_count,
                "created_at": p.created_at.isoformat(),
            }
            for p in profiles
        ],
        "plugin_configs": [
            {
                "id": pc.id,
                "plugin_name": pc.plugin_name,
                "config": pc.config,
            }
            for pc in plugin_configs
        ],
    }

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in proj.name).strip()
    filename = f"verdikt-export-{safe_name}.json"
    body = json.dumps(payload, indent=2, ensure_ascii=False)

    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ImportBody(BaseModel):
    version: int
    project: dict
    materials: list[dict] = []
    ratings: list[dict] = []
    profiles: list[dict] = []
    plugin_configs: list[dict] = []


@router.post("/import", status_code=201)
def import_project(
    body: ImportBody,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
) -> dict:
    if body.version != 1:
        raise HTTPException(status_code=422, detail=f"Unsupported export version: {body.version}")

    # Create project with a fresh ID
    old_project_id = body.project["id"]
    new_project_id = str(uuid.uuid4())

    dims = [RatingDimension(**d) for d in body.project.get("rating_dimensions", [])]
    proj = Project(
        id=new_project_id,
        name=body.project["name"],
        description=body.project.get("description"),
        domain=Domain(body.project.get("domain", "text")),
        rating_dimensions=dims,
        chunk_min_size=body.project.get("chunk_min_size", 600),
        chunk_max_size=body.project.get("chunk_max_size", 800),
        crystallisation_threshold=body.project.get("crystallisation_threshold", 50),
    )
    SQLiteProjectStore(session).create(proj)

    # Remap old IDs → new IDs
    mat_id_map: dict[str, str] = {}
    mat_store = SQLiteMaterialStore(session)
    for m in body.materials:
        old_id = m["id"]
        new_id = str(uuid.uuid4())
        mat_id_map[old_id] = new_id
        from datetime import datetime, timezone
        item = MaterialItem(
            id=new_id,
            project_id=new_project_id,
            source_plugin=m.get("source_plugin", ""),
            source_path=m.get("source_path"),
            work_title=m.get("work_title"),
            author=m.get("author"),
            url=m.get("url"),
            domain=m.get("domain", "text"),
            content_type=m.get("content_type", "text/plain"),
            pipeline_phase=PipelinePhase.INGESTED,
            content_hash=m.get("content_hash"),
            ingested_at=datetime.fromisoformat(m["ingested_at"]) if m.get("ingested_at") else datetime.now(timezone.utc),
            plugin_metadata=m.get("plugin_metadata", {}),
        )
        mat_store.save(item)

    rating_store = SQLiteRatingStore(session)
    for r in body.ratings:
        from datetime import datetime, timezone
        rating = Rating(
            id=str(uuid.uuid4()),
            project_id=new_project_id,
            chunk_id=r["chunk_id"],
            material_item_id=mat_id_map.get(r["material_item_id"], r["material_item_id"]),
            dimension_scores=r.get("dimension_scores", {}),
            skipped=r.get("skipped", False),
            skip_reason=r.get("skip_reason"),
            is_ai=r.get("is_ai", False),
            rated_at=datetime.fromisoformat(r["rated_at"]) if r.get("rated_at") else datetime.now(timezone.utc),
        )
        rating_store.save(rating)

    profile_store = SQLiteProfileStore(session)
    from verdikt.core.models import DimensionProfile
    for p in body.profiles:
        from datetime import datetime, timezone
        profile = PreferenceProfile(
            id=str(uuid.uuid4()),
            project_id=new_project_id,
            version=p.get("version", 1),
            dimensions=[DimensionProfile(**d) for d in p.get("dimensions", [])],
            overall_summary=p.get("overall_summary", ""),
            rating_count=p.get("rating_count", 0),
            created_at=datetime.fromisoformat(p["created_at"]) if p.get("created_at") else datetime.now(timezone.utc),
        )
        profile_store.save(profile)

    plugin_store = SQLitePluginConfigStore(session)
    for pc in body.plugin_configs:
        cfg = PluginConfig(
            id=str(uuid.uuid4()),
            project_id=new_project_id,
            plugin_name=pc["plugin_name"],
            config=pc.get("config", {}),
        )
        plugin_store.save(cfg)

    session.commit()

    return {
        "project_id": new_project_id,
        "materials_imported": len(body.materials),
        "ratings_imported": len(body.ratings),
        "profiles_imported": len(body.profiles),
        "plugin_configs_imported": len(body.plugin_configs),
        "note": "Pipeline must be re-run to regenerate chunks, embeddings, and clusters.",
    }
