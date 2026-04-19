from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_config, get_session
from verdikt.core.models import Domain, MaterialItem, PipelinePhase
from verdikt.plugins.filedrop import FileDropPlugin, _EXT_TO_CONTENT_TYPE
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore

import chromadb as _chromadb

router = APIRouter(prefix="/api/projects/{project_id}/works", tags=["works"])


def _work_response(item: MaterialItem) -> dict:
    return {
        "id": item.id,
        "project_seq": item.project_seq,
        "source_plugin": item.source_plugin,
        "source_path": item.source_path,
        "work_title": item.work_title,
        "author": item.author,
        "url": item.url,
        "domain": item.domain,
        "content_type": item.content_type,
        "pipeline_phase": item.pipeline_phase,
        "content_hash": item.content_hash,
        "ingested_at": item.ingested_at.isoformat(),
    }


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.get("")
def list_works(
    project_id: str,
    phase: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    proj = _get_project_or_404(project_id, session)
    phase_filter = PipelinePhase(phase) if phase else None
    items = SQLiteMaterialStore(session).list_by_project(proj.id, phase=phase_filter)
    return [_work_response(i) for i in items]


class IngestRequest(BaseModel):
    path: str


@router.post("/ingest", status_code=201)
def ingest_path(
    project_id: str,
    body: IngestRequest,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    ingest_path = Path(body.path).resolve()
    if not ingest_path.is_dir():
        raise HTTPException(status_code=422, detail=f"Directory not found: {ingest_path}")

    store = SQLiteMaterialStore(session)
    added = updated = skipped = 0
    for item in FileDropPlugin(str(ingest_path)).fetch(proj.id):
        existing = (
            store.get_by_source(proj.id, item.source_plugin, item.source_path)
            if item.source_path else None
        )
        if existing is None:
            store.save(item)
            added += 1
        elif existing.content_hash != item.content_hash:
            store.update_content(existing.id, item.content, item.content_hash)
            updated += 1
        else:
            skipped += 1
    session.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@router.delete("/{work_ref}", status_code=204)
def delete_work(
    project_id: str,
    work_ref: str,
    session: Session = Depends(get_session),
) -> None:
    proj = _get_project_or_404(project_id, session)
    mat_store = SQLiteMaterialStore(session)
    chunk_store = SQLiteChunkStore(session)

    if work_ref.isdigit():
        item = mat_store.get_by_seq(proj.id, int(work_ref))
    else:
        item = mat_store.get_by_source_path(proj.id, work_ref)
    if item is None:
        raise HTTPException(status_code=404, detail="Work not found")

    config = get_config()
    chroma = _chromadb.PersistentClient(path=str(config.chroma_path))
    vector_store = ChromaVectorStore(chroma, f"project_{proj.id}")
    chunks = chunk_store.list_by_material(item.id)
    vector_store.delete_items([c.id for c in chunks])
    chunk_store.delete_by_material(item.id)
    mat_store.delete(item.id)
    session.commit()
