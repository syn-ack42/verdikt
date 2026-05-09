from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

log = logging.getLogger(__name__)

# project_id → {phase, updated, unchanged} — cleared when done
_running_updates: dict[str, dict] = {}

# (plugin_name + config_hash) → plugin instance — keeps session/cookies alive across calls
_plugin_instance_cache: dict[str, object] = {}


_RUNTIME_CONFIG_KEYS = {"_storage_root", "_storage_backend"}


def _get_cached_plugin(cls, plugin_name: str, config: dict) -> object:
    serialisable = {k: v for k, v in config.items() if k not in _RUNTIME_CONFIG_KEYS}
    config_hash = hashlib.sha256(json.dumps(serialisable, sort_keys=True).encode()).hexdigest()
    key = f"{plugin_name}:{config_hash}"
    if key not in _plugin_instance_cache:
        log.info("plugin-cache: creating new instance for %s (%s)", plugin_name, key[:16])
        _plugin_instance_cache[key] = cls(config)
    else:
        log.info("plugin-cache: reusing cached instance for %s", plugin_name)
    return _plugin_instance_cache[key]


def _enrich_config(plugin_name: str, config: dict, backend: StorageBackend, domain: str = "text") -> dict:
    """Inject runtime-only values into plugin config (not stored in DB)."""
    if plugin_name == "storage":
        return {
            **config,
            "_storage_root": str(backend.resolve("/")),
            "_storage_backend": backend,
            "_domain": domain,
        }
    return config


def _friendly_error(exc: Exception) -> str:
    """Convert low-level network exceptions into human-readable messages."""
    msg = str(exc)
    msg_lower = msg.lower()
    if "timed out" in msg_lower or "operation timed out" in msg_lower or "curl: (28)" in msg:
        return "AO3 did not respond in time. The site may be slow or temporarily unavailable — please wait a moment and try again."
    if "curl: (6)" in msg or "could not resolve" in msg_lower or "name or service not known" in msg_lower:
        return "Could not reach AO3 — check your internet connection and try again."
    if "curl: (35)" in msg or "ssl" in msg_lower or "certificate" in msg_lower:
        return "Secure connection to AO3 failed. Try again in a moment."
    if "curl: (7)" in msg or "failed to connect" in msg_lower or "connection refused" in msg_lower:
        return "Could not connect to AO3. The site may be down — try again later."
    if "429" in msg or "too many requests" in msg_lower:
        return "AO3 rate-limited this request. Wait a few minutes before trying again."
    if "403" in msg or "forbidden" in msg_lower:
        return "AO3 blocked the request (403 Forbidden). Try again later."
    return f"Unexpected error: {msg}"


from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_config, get_current_user, get_session, get_storage
from verdikt.core.user_models import AuthenticatedUser
from verdikt.core.models import Domain, MaterialItem, PipelinePhase, PluginConfig
from verdikt.plugins.filedrop import FileDropPlugin, _EXT_TO_CONTENT_TYPE
from verdikt.plugins.storage import StoragePlugin
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
        "plugin_metadata": item.plugin_metadata,
    }


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


# Sort-field → SQL column expression (safe allowlist; user input never interpolated)
_SORT_COLS: dict[str, str] = {
    "seq":         "m.project_seq",
    "name":        "LOWER(m.work_title)",
    "ingested_at": "m.ingested_at",
    "phase":       "m.pipeline_phase",
    "human_rated": "COALESCE(rt.human_rated, 0)",
    "ai_rated":    "COALESCE(rt.ai_rated, 0)",
    "overall:avg": "rs.overall_avg",
    "overall:max": "rs.overall_max",
    "overall:min": "rs.overall_min",
}


@router.get("")
def list_works(
    project_id: str,
    phase: str | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> dict:
    from sqlalchemy import text as _text
    from verdikt.storage.orm import ChunkRow, RatingRow as _RatingRow

    _get_project_or_404(project_id, session)
    pid = project_id
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    # Determine sort column and whether this is a dim: sort
    dim_name: str | None = None
    if sort_by and sort_by.startswith("dim:"):
        # dim:<DimName>:<stat>  — use per-dimension avg
        parts = sort_by.split(":", 2)
        dim_name = parts[1] if len(parts) >= 2 else None
        order_col = "COALESCE(ds.dim_sort_val, 0)"
    else:
        order_col = _SORT_COLS.get(sort_by or "seq", "m.project_seq")

    # Build optional dim-sort subquery fragment
    dim_join = ""
    params: dict = {"pid": pid}
    if dim_name:
        dim_join = (
            "LEFT JOIN ("
            "  SELECT r.material_item_id, AVG(j.value) AS dim_sort_val"
            "  FROM ratings r, json_each(r.dimension_scores) j"
            "  WHERE r.project_id = :pid AND r.skipped = 0 AND j.key = :dim_name"
            "  GROUP BY r.material_item_id"
            ") ds ON m.id = ds.material_item_id"
        )
        params["dim_name"] = dim_name

    phase_clause = ""
    if phase:
        phase_clause = "AND m.pipeline_phase = :phase"
        params["phase"] = phase

    base_sql = f"""
        FROM material_items m
        LEFT JOIN (
            SELECT material_item_id,
                   COUNT(*) AS chunk_count,
                   COUNT(DISTINCT cluster_id) AS cluster_count
            FROM chunks WHERE project_id = :pid GROUP BY material_item_id
        ) ch ON m.id = ch.material_item_id
        LEFT JOIN (
            SELECT material_item_id,
                SUM(CASE WHEN is_ai=0 AND skipped=0 THEN 1 ELSE 0 END) AS human_rated,
                SUM(CASE WHEN is_ai=1 AND skipped=0 THEN 1 ELSE 0 END) AS ai_rated
            FROM ratings WHERE project_id = :pid GROUP BY material_item_id
        ) rt ON m.id = rt.material_item_id
        LEFT JOIN (
            SELECT material_item_id, COUNT(*) AS discovered_chunks
            FROM discovery_ratings WHERE project_id = :pid GROUP BY material_item_id
        ) dr ON m.id = dr.material_item_id
        LEFT JOIN (
            SELECT r.material_item_id,
                AVG(j.value) AS overall_avg,
                MAX(j.value) AS overall_max,
                MIN(j.value) AS overall_min
            FROM ratings r, json_each(r.dimension_scores) j
            WHERE r.project_id = :pid AND r.skipped = 0
              AND (r.is_ai = 1 OR NOT EXISTS (
                  SELECT 1 FROM ratings r2
                  WHERE r2.chunk_id = r.chunk_id AND r2.project_id = :pid
                    AND r2.is_ai = 1 AND r2.skipped = 0
              ))
              AND NOT EXISTS (
                  SELECT 1 FROM ratings r3
                  WHERE r3.chunk_id = r.chunk_id AND r3.project_id = :pid
                    AND r3.is_ai = r.is_ai AND r3.skipped = 0
                    AND r3.rated_at > r.rated_at
              )
            GROUP BY r.material_item_id
        ) rs ON m.id = rs.material_item_id
        {dim_join}
        WHERE m.project_id = :pid {phase_clause}
    """

    total_row = session.execute(_text(f"SELECT COUNT(*) {base_sql}"), params).scalar_one()

    select_sql = f"""
        SELECT
            m.id, m.project_seq, m.source_plugin, m.source_path, m.work_title,
            m.author, m.url, m.domain, m.content_type, m.pipeline_phase,
            m.content_hash, m.ingested_at, m.plugin_metadata_json,
            COALESCE(ch.chunk_count, 0)     AS total_chunks,
            COALESCE(ch.cluster_count, 0)   AS cluster_count,
            COALESCE(rt.human_rated, 0)     AS human_rated,
            COALESCE(rt.ai_rated,   0)      AS ai_rated,
            COALESCE(dr.discovered_chunks, 0) AS discovered_chunks,
            rs.overall_avg, rs.overall_max, rs.overall_min
        {base_sql}
        ORDER BY {order_col} {direction}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset
    rows = session.execute(_text(select_sql), params).mappings().all()

    if not rows:
        return {"total": total_row, "items": []}

    page_ids = [r["id"] for r in rows]

    # Ratings for page items only — for dim_stats breakdown
    rating_rows = (
        session.query(_RatingRow)
        .filter(_RatingRow.material_item_id.in_(page_ids), _RatingRow.skipped.is_(False))
        .all()
    )
    # Chunk descriptions for page items only
    desc_rows = (
        session.query(ChunkRow.material_item_id, ChunkRow.position, ChunkRow.description)
        .filter(ChunkRow.material_item_id.in_(page_ids), ChunkRow.description.isnot(None))
        .order_by(ChunkRow.material_item_id, ChunkRow.position)
        .all()
    )

    # Index by material_item_id, then deduplicate per chunk (human preferred over AI)
    ratings_by_mat: dict[str, list] = {}
    for rr in rating_rows:
        ratings_by_mat.setdefault(rr.material_item_id, []).append(rr)

    def _dedup_ratings(rrs: list) -> list:
        """Per chunk, keep the AI rating if one exists, otherwise the human rating."""
        best: dict[str, object] = {}
        for rr in rrs:
            existing = best.get(rr.chunk_id)
            if existing is None or (not existing.is_ai and rr.is_ai):
                best[rr.chunk_id] = rr
        return list(best.values())

    descs_by_mat: dict[str, list] = {}
    for dr in desc_rows:
        descs_by_mat.setdefault(dr.material_item_id, []).append(dr)

    def _dim_stats(mat_id: str) -> dict:
        dim_data: dict[str, list[float]] = {}
        for rr in _dedup_ratings(ratings_by_mat.get(mat_id, [])):
            try:
                scores = json.loads(rr.dimension_scores) if isinstance(rr.dimension_scores, str) else rr.dimension_scores
            except Exception:
                continue
            for dim, score in scores.items():
                dim_data.setdefault(dim, []).append(float(score))
        return {
            dim: {
                "avg": round(sum(vals) / len(vals), 3),
                "max": round(max(vals), 3),
                "min": round(min(vals), 3),
            }
            for dim, vals in dim_data.items()
        }

    def _overall_stats(mat_id: str) -> tuple[float | None, float | None, float | None]:
        all_scores = []
        for rr in _dedup_ratings(ratings_by_mat.get(mat_id, [])):
            try:
                scores = json.loads(rr.dimension_scores) if isinstance(rr.dimension_scores, str) else rr.dimension_scores
                all_scores.extend(scores.values())
            except Exception:
                continue
        if not all_scores:
            return None, None, None
        return (
            round(sum(all_scores) / len(all_scores), 3),
            round(max(all_scores), 3),
            round(min(all_scores), 3),
        )

    items = []
    for r in rows:
        mat_id = r["id"]
        chunk_descs = [
            {"position": dr.position, "description": dr.description}
            for dr in descs_by_mat.get(mat_id, [])
        ]
        try:
            plugin_meta = json.loads(r["plugin_metadata_json"] or "{}")
        except Exception:
            plugin_meta = {}
        overall_avg, overall_max, overall_min = _overall_stats(mat_id)
        item = {
            "id": mat_id,
            "project_seq": r["project_seq"],
            "source_plugin": r["source_plugin"],
            "source_path": r["source_path"],
            "work_title": r["work_title"],
            "author": r["author"],
            "url": r["url"],
            "domain": r["domain"],
            "content_type": r["content_type"],
            "pipeline_phase": r["pipeline_phase"],
            "content_hash": r["content_hash"],
            "ingested_at": r["ingested_at"],
            "plugin_metadata": plugin_meta,
            "total_chunks": r["total_chunks"],
            "cluster_count": r["cluster_count"],
            "human_rated": r["human_rated"],
            "ai_rated": r["ai_rated"],
            "discovered_chunks": r["discovered_chunks"],
            "overall_avg": overall_avg,
            "overall_max": overall_max,
            "overall_min": overall_min,
            "dim_stats": _dim_stats(mat_id),
            "first_description": chunk_descs[0]["description"] if chunk_descs else None,
            "chunk_descriptions": chunk_descs,
        }
        items.append(item)

    return {"total": total_row, "items": items}


class IngestRequest(BaseModel):
    storage_paths: list[str]  # storage-relative paths (files or directories)


def _ingest_fs_path(
    fs_path: Path,
    project_id: str,
    store: SQLiteMaterialStore,
    source_path_override: str | None = None,
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
        if source_path_override and item.source_path != source_path_override:
            item = item.model_copy(update={"source_path": source_path_override})
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
    storage_root = backend.resolve("/")
    total_added = total_updated = total_skipped = 0

    for storage_path in body.storage_paths:
        if not backend.exists(storage_path):
            raise HTTPException(status_code=422, detail=f"Storage path not found: {storage_path}")
        fs_path = backend.resolve(storage_path)
        # For encrypted backends, fs_path is a temp file whose path must not be
        # used as the stable source_path identifier — use the canonical path instead.
        canonical = str(storage_root / storage_path.lstrip("/")) if not fs_path.is_dir() else None
        a, u, s = _ingest_fs_path(fs_path, proj.id, store, source_path_override=canonical)
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
) -> dict:
    proj = _get_project_or_404(project_id, session)
    cfgs = SQLitePluginConfigStore(session).list_by_project(proj.id)
    return {
        cfg.plugin_name: {"id": cfg.id, "project_id": cfg.project_id, "plugin_name": cfg.plugin_name, "config": cfg.config}
        for cfg in cfgs
    }


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
    backend: StorageBackend | None = None,
    domain: str = "text",
) -> tuple[int, int, int]:
    try:
        cls = get_plugin(plugin_name)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Unknown plugin: {plugin_name!r}")
    full_config = _enrich_config(plugin_name, config, backend, domain) if backend else config
    plugin = _get_cached_plugin(cls, plugin_name, full_config)
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
    backend: StorageBackend = Depends(get_storage),
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

    added, updated, skipped = _run_plugin_ingest(proj.id, body.plugin_name, saved_cfg.config, mat_store, backend, getattr(proj.domain, "value", proj.domain))
    session.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@router.post("/ingest-plugin/stream")
def ingest_from_plugin_stream(
    project_id: str,
    body: PluginIngestRequest,
    session: Session = Depends(get_session),
    backend: StorageBackend = Depends(get_storage),
) -> StreamingResponse:
    proj = _get_project_or_404(project_id, session)
    cfg_store = SQLitePluginConfigStore(session)
    mat_store = SQLiteMaterialStore(session)

    if body.config is not None:
        cfg_store.save(PluginConfig(
            project_id=proj.id,
            plugin_name=body.plugin_name,
            config=body.config,
            updated_at=datetime.now(timezone.utc),
        ))

    saved_cfg = cfg_store.get(proj.id, body.plugin_name)
    if saved_cfg is None:
        def _err() -> Generator[str, None, None]:
            yield f"data: {json.dumps({'error': 'No plugin config found. Provide config in request body.'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    try:
        cls = get_plugin(body.plugin_name)
    except KeyError:
        def _err2() -> Generator[str, None, None]:
            yield f"data: {json.dumps({'error': f'Unknown plugin: {body.plugin_name!r}'})}\n\n"
        return StreamingResponse(_err2(), media_type="text/event-stream")

    plugin = _get_cached_plugin(cls, body.plugin_name, _enrich_config(body.plugin_name, saved_cfg.config, backend, getattr(proj.domain, "value", proj.domain)))
    total = plugin.estimate_count()

    def event_stream() -> Generator[str, None, None]:
        added = updated = skipped = 0
        try:
            if total is not None:
                yield f"data: {json.dumps({'total': total})}\n\n"
            # Index existing items by work_id for O(1) dedup
            existing_items = mat_store.list_by_source_plugin(proj.id, body.plugin_name)
            by_work_id = {i.plugin_metadata["work_id"]: i for i in existing_items if i.plugin_metadata.get("work_id")}
            by_source = {i.source_path: i for i in existing_items if i.source_path}
            for item in plugin.fetch(proj.id):
                wid = item.plugin_metadata.get("work_id")
                existing = by_work_id.get(wid) if wid else (by_source.get(item.source_path) if item.source_path else None)
                label = item.work_title or item.source_path or wid or ""
                if existing is None:
                    mat_store.save(item)
                    added += 1
                    status = "added"
                elif existing.content_hash != item.content_hash:
                    mat_store.update_content(existing.id, item.content, item.content_hash, item.plugin_metadata or None)
                    updated += 1
                    status = "updated"
                else:
                    mat_store.update_plugin_metadata(existing.id, item.plugin_metadata)
                    skipped += 1
                    status = "unchanged"
                session.commit()
                yield f"data: {json.dumps({'work': label, 'status': status, 'added': added, 'updated': updated, 'skipped': skipped})}\n\n"
        except Exception as exc:
            log.exception("ingest-plugin stream error for project %s", proj.id)
            yield f"data: {json.dumps({'error': _friendly_error(exc)})}\n\n"
            return
        yield f"data: {json.dumps({'complete': True, 'added': added, 'updated': updated, 'skipped': skipped})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/update-plugin/status")
def update_plugin_status(
    project_id: str,
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    state = _running_updates.get(project_id)
    if state:
        return {"running": True, **state}
    return {"running": False, "phase": None, "updated": 0, "unchanged": 0}


@router.post("/update-plugin/stream")
def update_from_plugin_stream(
    project_id: str,
    session: Session = Depends(get_session),
    backend: StorageBackend = Depends(get_storage),
) -> StreamingResponse:
    proj = _get_project_or_404(project_id, session)
    cfg_store = SQLitePluginConfigStore(session)
    mat_store = SQLiteMaterialStore(session)

    cfgs = cfg_store.list_by_project(proj.id)
    if not cfgs:
        def _err() -> Generator[str, None, None]:
            yield f"data: {json.dumps({'error': 'No plugin config saved for this project.'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    cfg = cfgs[0]
    try:
        cls = get_plugin(cfg.plugin_name)
    except KeyError:
        def _err2() -> Generator[str, None, None]:
            yield f"data: {json.dumps({'error': f'Unknown plugin: {cfg.plugin_name!r}'})}\n\n"
        return StreamingResponse(_err2(), media_type="text/event-stream")

    plugin = _get_cached_plugin(cls, cfg.plugin_name, _enrich_config(cfg.plugin_name, cfg.config, backend, getattr(proj.domain, "value", proj.domain)))
    stored = mat_store.list_by_source_plugin(proj.id, cfg.plugin_name)
    work_ids = [i.plugin_metadata["work_id"] for i in stored if i.plugin_metadata.get("work_id")]
    stored_by_work_id = {i.plugin_metadata["work_id"]: i for i in stored if i.plugin_metadata.get("work_id")}
    log.info("update-plugin stream: project=%s plugin=%s trackable=%d", proj.id, cfg.plugin_name, len(work_ids))

    def event_stream() -> Generator[str, None, None]:
        _running_updates[proj.id] = {"phase": "checking", "updated": 0, "unchanged": 0}
        try:
            yield f"data: {json.dumps({'phase': 'checking', 'total': len(work_ids)})}\n\n"

            updated_ats = plugin.get_updated_ats(work_ids)

            needs_update: list[str] = []
            date_unchanged = 0
            for wid in work_ids:
                remote_date = updated_ats.get(wid)
                stored_item = stored_by_work_id[wid]
                stored_date_str = stored_item.plugin_metadata.get("source_updated_at")
                stored_date = datetime.fromisoformat(stored_date_str) if stored_date_str else None
                # Compare at day granularity: the work page only gives YYYY-MM-DD (midnight UTC)
                # while the search result carries a Unix timestamp. Same calendar day = unchanged.
                if remote_date is not None and stored_date is not None and remote_date.date() <= stored_date.date():
                    decision = "unchanged"
                    date_unchanged += 1
                else:
                    decision = "needs_update"
                    needs_update.append(wid)
                log.debug(
                    "update-check work_id=%s remote_date=%s stored_date=%s -> %s",
                    wid, remote_date, stored_date, decision,
                )

            log.info("update-plugin stream: %d need re-fetch, %d up-to-date by date", len(needs_update), date_unchanged)
            _running_updates[proj.id] = {"phase": "fetching", "updated": 0, "unchanged": date_unchanged}
            yield f"data: {json.dumps({'phase': 'fetching', 'needs_update': len(needs_update), 'unchanged': date_unchanged})}\n\n"

            updated = 0
            unchanged = date_unchanged
            for item in plugin.fetch_by_ids(proj.id, needs_update, date_hints=updated_ats):
                wid = item.plugin_metadata.get("work_id")
                existing = stored_by_work_id.get(wid)
                label = item.work_title or item.source_path or wid
                if existing is None:
                    mat_store.save(item)
                    session.commit()
                    updated += 1
                    status = "updated"
                elif existing.content_hash != item.content_hash:
                    mat_store.update_content(existing.id, item.content, item.content_hash, item.plugin_metadata or None)
                    session.commit()
                    updated += 1
                    status = "updated"
                else:
                    if item.plugin_metadata:
                        mat_store.update_plugin_metadata(existing.id, item.plugin_metadata)
                        session.commit()
                    unchanged += 1
                    status = "unchanged"
                _running_updates[proj.id] = {"phase": "fetching", "updated": updated, "unchanged": unchanged}
                yield f"data: {json.dumps({'work': label, 'status': status, 'updated': updated, 'unchanged': unchanged})}\n\n"

            # Discover new items in folder-mode selections (storage plugin) or any plugin that supports it
            new_ids = plugin.get_new_work_ids(set(work_ids))
            if new_ids:
                log.info("update-plugin stream: discovering %d new items", len(new_ids))
                for item in plugin.fetch_by_ids(proj.id, new_ids):
                    wid = item.plugin_metadata.get("work_id")
                    label = item.work_title or item.source_path or wid
                    mat_store.save(item)
                    session.commit()
                    updated += 1
                    _running_updates[proj.id] = {"phase": "fetching", "updated": updated, "unchanged": unchanged}
                    yield f"data: {json.dumps({'work': label, 'status': 'added', 'updated': updated, 'unchanged': unchanged})}\n\n"

            yield f"data: {json.dumps({'complete': True, 'updated': updated, 'unchanged': unchanged})}\n\n"

        except Exception as exc:
            log.exception("update-plugin stream error for project %s", proj.id)
            yield f"data: {json.dumps({'error': _friendly_error(exc)})}\n\n"
            return
        finally:
            _running_updates.pop(proj.id, None)

        yield f"data: {json.dumps({'complete': True, 'updated': updated, 'unchanged': unchanged})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chunk/{chunk_id}")
def get_chunk_content(
    project_id: str,
    chunk_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Return content + domain for a single chunk. Used by the ratings modal edit view."""
    import base64
    chunk_store = SQLiteChunkStore(session)
    chunk = chunk_store.get(chunk_id)
    if chunk is None or chunk.project_id != project_id:
        raise HTTPException(status_code=404, detail="Chunk not found")
    if isinstance(chunk.content, bytes):
        return {"content": base64.b64encode(chunk.content).decode(), "domain": "image"}
    return {"content": chunk.content, "domain": "text"}


@router.get("/{work_ref}/detail")
def get_work_detail(
    project_id: str,
    work_ref: str,
    session: Session = Depends(get_session),
    backend: StorageBackend = Depends(get_storage),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    mat_store = SQLiteMaterialStore(session)

    if work_ref.isdigit():
        item = mat_store.get_by_seq(proj.id, int(work_ref))
    else:
        item = mat_store.get_by_source_path(proj.id, work_ref)
    if item is None:
        raise HTTPException(status_code=404, detail="Work not found")

    import base64
    content: str | None = None
    content_is_image = False
    if isinstance(item.content, bytes):
        from verdikt.core.models import Domain
        if getattr(item, "domain", None) == Domain.IMAGE or getattr(item, "domain", None) == "image":
            content = base64.b64encode(item.content).decode()
            content_is_image = True
        else:
            try:
                content = item.content.decode("utf-8", errors="replace")
            except Exception:
                content = None
    else:
        content = item.content

    # For storage plugin, convert absolute fs path to storage-relative path if possible
    storage_path: str | None = None
    if item.source_plugin in ("storage", "filedrop") and item.source_path:
        try:
            storage_root = backend.resolve("/")
            abs_path = Path(item.source_path)
            rel = abs_path.relative_to(storage_root)
            storage_path = "/" + str(rel).replace("\\", "/")
        except (ValueError, Exception):
            pass

    return {
        **_work_response(item),
        "content": content,
        "content_is_image": content_is_image,
        "storage_path": storage_path,
    }


@router.get("/{work_ref}/chunks")
def get_work_chunks(
    project_id: str,
    work_ref: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Return all chunks for a work with any associated ratings."""
    import base64
    proj = _get_project_or_404(project_id, session)
    mat_store = SQLiteMaterialStore(session)

    if work_ref.isdigit():
        item = mat_store.get_by_seq(proj.id, int(work_ref))
    else:
        item = mat_store.get_by_source_path(proj.id, work_ref)
    if item is None:
        raise HTTPException(status_code=404, detail="Work not found")

    chunk_store = SQLiteChunkStore(session)
    rating_store = SQLiteRatingStore(session)

    chunks = sorted(chunk_store.list_by_material(item.id), key=lambda c: c.position)
    chunk_count = len(chunks)

    # Build rating index: chunk_id → best rating (prefer AI over human)
    all_ratings = [r for r in rating_store.list_by_project(project_id) if not r.skipped and r.material_item_id == item.id]
    rating_by_chunk: dict[str, object] = {}
    for r in all_ratings:
        existing = rating_by_chunk.get(r.chunk_id)
        if existing is None or (not existing.is_ai and r.is_ai):
            rating_by_chunk[r.chunk_id] = r

    # Track which chunks also have a human rating (shown when AI is displayed)
    human_rated_chunk_ids = {r.chunk_id for r in all_ratings if not r.is_ai}

    result = []
    for chunk in chunks:
        if isinstance(chunk.content, bytes):
            content = base64.b64encode(chunk.content).decode()
            domain = "image"
        else:
            content = chunk.content
            domain = "text"

        r = rating_by_chunk.get(chunk.id)
        rating_dict = None
        if r is not None:
            avg = (sum(r.dimension_scores.values()) / len(r.dimension_scores)) if r.dimension_scores else None
            rating_dict = {
                "rating_id": r.id,
                "dimension_scores": r.dimension_scores,
                "avg_score": round(avg, 2) if avg is not None else None,
                "is_ai": r.is_ai,
                "explanations": r.explanations,
                "rated_at": r.rated_at.isoformat(),
                "also_human_rated": r.is_ai and (chunk.id in human_rated_chunk_ids),
            }

        result.append({
            "chunk_id": chunk.id,
            "material_item_id": item.id,
            "position": chunk.position,
            "chunk_count": chunk_count,
            "cluster_id": chunk.cluster_id,
            "content": content,
            "domain": domain,
            "description": chunk.description,
            "rating": rating_dict,
        })

    return result


@router.delete("/{work_ref}", status_code=204)
def delete_work(
    project_id: str,
    work_ref: str,
    user: AuthenticatedUser = Depends(get_current_user),
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
    chroma = _chromadb.PersistentClient(path=str(config.user_chroma_path(user.id)))
    vector_store = ChromaVectorStore(chroma, f"project_{proj.id}")
    chunks = chunk_store.list_by_material(item.id)
    vector_store.delete_items([c.id for c in chunks])
    SQLiteRatingStore(session).delete_by_material(item.id)
    chunk_store.delete_by_material(item.id)
    mat_store.delete(item.id)
    session.commit()
