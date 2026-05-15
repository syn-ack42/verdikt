from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_cached_chroma_client, get_config, get_current_user, get_session
from verdikt.core.user_models import AuthenticatedUser
from verdikt.inference.resolver import resolve_embedder
from verdikt.core.models import Domain
from verdikt.pipeline.chunker import IdentityChunker, TextChunker


def _make_chunker(proj):
    if getattr(proj.domain, "value", proj.domain) == Domain.IMAGE.value:
        return IdentityChunker()
    return TextChunker(min_words=proj.chunk_min_size, max_words=proj.chunk_max_size)
from verdikt.pipeline.flows import run_pipeline_flow
from verdikt.pipeline.runner import PipelineRunner
from verdikt.plugins.registry import get_plugin
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLitePluginConfigStore, SQLiteProjectStore

router = APIRouter(prefix="/api/projects/{project_id}/pipeline", tags=["pipeline"])


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _build_content_fetchers(project_id: str, session) -> dict:
    """Build a {plugin_name: plugin_instance} dict for plugins that support remote content."""
    fetchers: dict = {}
    try:
        cfg_store = SQLitePluginConfigStore(session)
        for cfg in cfg_store.list_by_project(project_id):
            try:
                cls = get_plugin(cfg.plugin_name)
            except KeyError:
                continue
            if cls.supports_remote_content():
                fetchers[cfg.plugin_name] = cls(cfg.config)
    except Exception:
        pass
    return fetchers


@router.post("/run")
def run_pipeline(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    config = get_config()

    chroma = get_cached_chroma_client(user.id)
    runner = PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=ChromaVectorStore(chroma, f"project_{proj.id}"),
        embedder=resolve_embedder(proj, config, auth_session, user_id=user.id),
        chunker=_make_chunker(proj),
        content_fetchers=_build_content_fetchers(proj.id, session),
    )
    result = run_pipeline_flow(project_id=proj.id, runner=runner)
    session.commit()

    return {
        "project_id": proj.id,
        "total_processed": result.total_processed,
        "phases": [
            {"phase": p.phase, "items_processed": p.items_processed}
            for p in result.phases
        ],
    }


@router.post("/run/stream")
def run_pipeline_stream(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> StreamingResponse:
    proj = _get_project_or_404(project_id, session)
    config = get_config()
    chroma = get_cached_chroma_client(user.id)
    runner = PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=ChromaVectorStore(chroma, f"project_{proj.id}"),
        embedder=resolve_embedder(proj, config, auth_session, user_id=user.id),
        chunker=_make_chunker(proj),
        content_fetchers=_build_content_fetchers(proj.id, session),
    )

    def event_stream() -> Generator[str, None, None]:
        total = 0
        for phase_name, stream_fn in [
            ("chunk", runner._chunk_stream),
            ("embed", runner._embed_stream),
            ("cluster", runner._cluster_stream),
        ]:
            try:
                items_processed = 0
                for event in stream_fn(proj.id):
                    etype = event["type"]
                    if etype == "start":
                        yield f"data: {json.dumps({'phase': phase_name, 'status': 'running', 'total': event['total']})}\n\n"
                    elif etype == "progress":
                        yield f"data: {json.dumps({'phase': phase_name, 'status': 'progress', 'current': event['current'], 'total': event['total']})}\n\n"
                    elif etype == "done":
                        items_processed = event["items_processed"]
                session.commit()
                total += items_processed
                yield f"data: {json.dumps({'phase': phase_name, 'status': 'done', 'items_processed': items_processed})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'phase': phase_name, 'status': 'error', 'error': str(exc)})}\n\n"
                return
        yield f"data: {json.dumps({'complete': True, 'total_processed': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
