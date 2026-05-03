"""Batched ingest router — fetch → pipeline → repeat, with persistent resume/stop/reset."""
from __future__ import annotations

import json
import logging
from collections.abc import Generator
from datetime import datetime, timezone

import chromadb as _chromadb
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from verdikt.api.deps import get_config, get_current_user, get_session
from verdikt.core.models import Domain, PipelinePhase
from verdikt.core.user_models import AuthenticatedUser
from verdikt.inference.resolver import resolve_embedder
from verdikt.pipeline.chunker import IdentityChunker, TextChunker
from verdikt.pipeline.runner import PipelineRunner
from verdikt.plugins.registry import get_plugin
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.sqlite import (
    SQLiteChunkStore,
    SQLiteMaterialStore,
    SQLitePluginBatchStateStore,
    SQLitePluginConfigStore,
    SQLiteProjectStore,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/batch-ingest", tags=["batch-ingest"])

# In-memory stop flags: project_id → True means "stop after this batch"
_stop_flags: dict[str, bool] = {}


def _set_stop(project_id: str) -> None:
    _stop_flags[project_id] = True


def _clear_stop(project_id: str) -> None:
    _stop_flags.pop(project_id, None)


def _should_stop(project_id: str) -> bool:
    return _stop_flags.get(project_id, False)


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _find_batch_plugin(project_id: str, session: Session):
    """Return (plugin_name, cls, config) for the first batch-capable plugin, or None."""
    for cfg in SQLitePluginConfigStore(session).list_by_project(project_id):
        try:
            cls = get_plugin(cfg.plugin_name)
        except KeyError:
            continue
        if cls.supports_batched_ingest():
            return cfg.plugin_name, cls, cfg.config
    return None


def _make_chunker(proj):
    if getattr(proj.domain, "value", proj.domain) == Domain.IMAGE.value:
        return IdentityChunker()
    return TextChunker(min_words=proj.chunk_min_size, max_words=proj.chunk_max_size)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.get("/status")
def get_batch_status(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    result = _find_batch_plugin(project_id, session)
    if result is None:
        return {"supported": False}
    plugin_name, _, _ = result
    row = SQLitePluginBatchStateStore(session).get(project_id, plugin_name)
    return {
        "supported": True,
        "plugin": plugin_name,
        "status": row.status if row else "idle",
        "fetched": row.fetched if row else 0,
        "total": row.total if row else None,
    }


@router.post("/stop")
def stop_batch(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    _set_stop(project_id)
    return {"ok": True}


@router.post("/reset", status_code=200)
def reset_batch(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    result = _find_batch_plugin(project_id, session)
    if result is None:
        raise HTTPException(status_code=422, detail="No batch-ingest capable plugin configured")
    plugin_name, _, _ = result
    _clear_stop(project_id)
    SQLitePluginBatchStateStore(session).delete(project_id, plugin_name)
    session.commit()
    return {"status": "idle"}


@router.post("/start/stream")
def start_batch_stream(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    proj = _get_project_or_404(project_id, session)
    config = get_config()

    result = _find_batch_plugin(project_id, session)
    if result is None:
        raise HTTPException(status_code=422, detail="No batch-ingest capable plugin configured")
    plugin_name, plugin_cls, plugin_config = result
    plugin = plugin_cls(plugin_config)

    chroma = _chromadb.PersistentClient(path=str(config.user_chroma_path(user.id)))
    mat_store = SQLiteMaterialStore(session)
    chunk_store = SQLiteChunkStore(session)
    vector_store = ChromaVectorStore(chroma, f"project_{proj.id}")
    content_fetchers = {plugin_name: plugin} if plugin_cls.supports_remote_content() else {}
    runner = PipelineRunner(
        material_store=mat_store,
        chunk_store=chunk_store,
        vector_store=vector_store,
        embedder=resolve_embedder(proj, config),
        chunker=_make_chunker(proj),
        content_fetchers=content_fetchers,
    )
    state_store = SQLitePluginBatchStateStore(session)

    def event_stream() -> Generator[str, None, None]:
        row = state_store.get(project_id, plugin_name)
        if row and row.status == "done":
            yield _sse({"type": "error", "error": "Run already complete. Reset first."})
            return

        current_state: dict | None = (
            json.loads(row.state_json) if row and row.status == "paused" else None
        )
        total_fetched: int = row.fetched if row else 0

        _clear_stop(project_id)
        state_store.upsert(project_id, plugin_name, current_state or {}, "running", total_fetched)
        session.commit()

        # Pre-load existing hashes so ingest_batch can skip re-downloading unchanged content
        existing_hashes = mat_store.list_source_hashes(project_id, plugin_name)

        batch_num = 0
        total_added = total_updated = total_unchanged = 0

        while True:
            # ── fetch one batch ────────────────────────────────────────────────
            try:
                items, next_state = plugin.ingest_batch(project_id, current_state, existing_hashes)
            except Exception as exc:
                log.exception("batch ingest: ingest_batch failed")
                yield _sse({"type": "error", "error": str(exc)})
                state_store.upsert(project_id, plugin_name, current_state or {}, "error", total_fetched)
                session.commit()
                return

            batch_num += 1
            batch_added = batch_updated = batch_unchanged = 0
            yield _sse({"type": "batch_start", "batch": batch_num})

            # ── upsert items ───────────────────────────────────────────────────
            for item in items:
                if not item.source_path:
                    continue
                existing = mat_store.get_by_source_path(project_id, item.source_path)
                if existing is None:
                    mat_store.save(item)
                    batch_added += 1
                    item_status = "added"
                elif existing.content_hash != item.content_hash:
                    mat_store.update_content(
                        existing.id,
                        item.content,
                        item.content_hash,
                        item.plugin_metadata,
                    )
                    batch_updated += 1
                    item_status = "updated"
                else:
                    batch_unchanged += 1
                    item_status = "unchanged"
                yield _sse({
                    "type": "item",
                    "work": item.work_title or item.source_path,
                    "status": item_status,
                    "batch_added": batch_added,
                    "batch_updated": batch_updated,
                    "batch_unchanged": batch_unchanged,
                })

            session.commit()
            total_added += batch_added
            total_updated += batch_updated
            total_unchanged += batch_unchanged
            total_fetched += len(items)

            yield _sse({
                "type": "batch_done",
                "batch": batch_num,
                "added": batch_added,
                "updated": batch_updated,
                "unchanged": batch_unchanged,
                "total_added": total_added,
                "total_updated": total_updated,
                "total_unchanged": total_unchanged,
                "total_fetched": total_fetched,
            })

            # ── run pipeline on newly ingested items ───────────────────────────
            if batch_added + batch_updated > 0:
                yield _sse({"type": "pipeline_start", "batch": batch_num})
                pipeline_ok = True
                for phase_name, stream_fn in [
                    ("chunk", runner._chunk_stream),
                    ("embed", runner._embed_stream),
                    ("cluster", runner._cluster_stream),
                ]:
                    try:
                        for event in stream_fn(proj.id):
                            etype = event.get("type")
                            if etype == "start":
                                yield _sse({"type": "pipeline_phase", "phase": phase_name, "status": "running", "total": event.get("total")})
                            elif etype == "progress":
                                yield _sse({"type": "pipeline_phase", "phase": phase_name, "status": "progress", "current": event["current"], "total": event["total"]})
                        session.commit()
                        yield _sse({"type": "pipeline_phase", "phase": phase_name, "status": "done"})
                    except Exception as exc:
                        yield _sse({"type": "pipeline_phase", "phase": phase_name, "status": "error", "error": str(exc)})
                        pipeline_ok = False
                        break
                if pipeline_ok:
                    yield _sse({"type": "pipeline_done", "batch": batch_num})

            # ── persist state and check completion / stop ──────────────────────
            current_state = next_state
            new_status = "done" if next_state is None else "running"
            state_store.upsert(project_id, plugin_name, next_state or {}, new_status, total_fetched)
            session.commit()

            if next_state is None:
                yield _sse({
                    "type": "complete",
                    "batches": batch_num,
                    "total_added": total_added,
                    "total_updated": total_updated,
                    "total_unchanged": total_unchanged,
                    "total_fetched": total_fetched,
                })
                break

            if _should_stop(project_id):
                _clear_stop(project_id)
                state_store.upsert(project_id, plugin_name, next_state, "paused", total_fetched)
                session.commit()
                yield _sse({
                    "type": "paused",
                    "batch": batch_num,
                    "total_fetched": total_fetched,
                })
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")
