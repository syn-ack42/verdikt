from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_config, get_session, get_storage
from verdikt.core.models import Domain, MaterialItem, PipelinePhase, PluginConfig
from verdikt.plugins.filedrop import FileDropPlugin, _EXT_TO_CONTENT_TYPE
from verdikt.plugins.registry import get_plugin
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.files import StorageBackend
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLitePluginConfigStore, SQLiteProjectStore, SQLiteRatingStore

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
    storage_paths: list[str]  # storage-relative paths (files or directories)


def _ingest_fs_path(
    fs_path: Path,
    project_id: str,
    store: SQLiteMaterialStore,
) -> tuple[int, int, int]:
    """Ingest a single resolved filesystem path (file or directory). Returns (added, updated, skipped)."""
    added = updated = skipped = 0
    if fs_path.is_dir():
        items = FileDropPlugin(str(fs_path)).fetch(project_id)
    elif fs_path.is_file() and fs_path.suffix.lower() in FileDropPlugin.SUPPORTED_EXTENSIONS:
        items = FileDropPlugin._fetch_single_file(fs_path, project_id)
    else:
        return 0, 0, 0

    for item in items:
        existing = (
            store.get_by_source(project_id, item.source_plugin, item.source_path)
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
    return added, updated, skipped


@router.post("/ingest", status_code=201)
def ingest_from_storage(
    project_id: str,
    body: IngestRequest,
    session: Session = Depends(get_session),
    backend: StorageBackend = Depends(get_storage),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    store = SQLiteMaterialStore(session)
    total_added = total_updated = total_skipped = 0

    for storage_path in body.storage_paths:
        if not backend.exists(storage_path):
            raise HTTPException(status_code=422, detail=f"Storage path not found: {storage_path}")
        fs_path = backend.resolve(storage_path)
        a, u, s = _ingest_fs_path(fs_path, proj.id, store)
        total_added += a
        total_updated += u
        total_skipped += s

    session.commit()
    return {"added": total_added, "updated": total_updated, "skipped": total_skipped}


class PluginConfigRequest(BaseModel):
    plugin_name: str
    config: dict


@router.get("/plugin-config")
def get_plugin_config(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict | None:
    proj = _get_project_or_404(project_id, session)
    cfgs = SQLitePluginConfigStore(session).list_by_project(proj.id)
    if not cfgs:
        return None
    cfg = cfgs[0]
    return {"id": cfg.id, "project_id": cfg.project_id, "plugin_name": cfg.plugin_name, "config": cfg.config}


@router.put("/plugin-config", status_code=200)
def save_plugin_config(
    project_id: str,
    body: PluginConfigRequest,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    try:
        get_plugin(body.plugin_name)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Unknown plugin: {body.plugin_name!r}")
    cfg = PluginConfig(
        project_id=proj.id,
        plugin_name=body.plugin_name,
        config=body.config,
        updated_at=datetime.now(timezone.utc),
    )
    saved = SQLitePluginConfigStore(session).save(cfg)
    session.commit()
    return {"id": saved.id, "project_id": saved.project_id, "plugin_name": saved.plugin_name, "config": saved.config}


class PluginIngestRequest(BaseModel):
    plugin_name: str
    config: dict | None = None


def _run_plugin_ingest(
    project_id: str,
    plugin_name: str,
    config: dict,
    store: SQLiteMaterialStore,
) -> tuple[int, int, int]:
    try:
        cls = get_plugin(plugin_name)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Unknown plugin: {plugin_name!r}")
    plugin = cls(config)
    added = updated = skipped = 0
    for item in plugin.fetch(project_id):
        existing = (
            store.get_by_source(project_id, item.source_plugin, item.source_path)
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
    return added, updated, skipped


@router.post("/ingest-plugin", status_code=201)
def ingest_from_plugin(
    project_id: str,
    body: PluginIngestRequest,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    cfg_store = SQLitePluginConfigStore(session)
    mat_store = SQLiteMaterialStore(session)

    if body.config is not None:
        cfg = PluginConfig(
            project_id=proj.id,
            plugin_name=body.plugin_name,
            config=body.config,
            updated_at=datetime.now(timezone.utc),
        )
        cfg_store.save(cfg)

    saved_cfg = cfg_store.get(proj.id, body.plugin_name)
    if saved_cfg is None:
        raise HTTPException(status_code=422, detail="No plugin config found. Provide config in request body.")

    added, updated, skipped = _run_plugin_ingest(proj.id, body.plugin_name, saved_cfg.config, mat_store)
    session.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@router.post("/update-plugin", status_code=200)
def update_from_plugin(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    cfg_store = SQLitePluginConfigStore(session)
    mat_store = SQLiteMaterialStore(session)

    cfgs = cfg_store.list_by_project(proj.id)
    if not cfgs:
        raise HTTPException(status_code=422, detail="No plugin config saved for this project.")

    cfg = cfgs[0]
    _, updated, unchanged = _run_plugin_ingest(proj.id, cfg.plugin_name, cfg.config, mat_store)
    session.commit()
    return {"updated": updated, "unchanged": unchanged}


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
    SQLiteRatingStore(session).delete_by_material(item.id)
    chunk_store.delete_by_material(item.id)
    mat_store.delete(item.id)
    session.commit()
