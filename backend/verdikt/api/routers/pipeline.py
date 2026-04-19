from __future__ import annotations

import json
from collections.abc import Generator

import chromadb as _chromadb
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from verdikt.api.deps import get_config, get_session
from verdikt.inference.embedder import SentenceTransformerEmbedder
from verdikt.pipeline.chunker import TextChunker
from verdikt.pipeline.flows import run_pipeline_flow
from verdikt.pipeline.runner import PipelineRunner
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore

router = APIRouter(prefix="/api/projects/{project_id}/pipeline", tags=["pipeline"])


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.post("/run")
def run_pipeline(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    config = get_config()

    chroma = _chromadb.PersistentClient(path=str(config.chroma_path))
    runner = PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=ChromaVectorStore(chroma, f"project_{proj.id}"),
        embedder=SentenceTransformerEmbedder(config.inference.embedding_model),
        chunker=TextChunker(min_words=proj.chunk_min_size, max_words=proj.chunk_max_size),
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


def _make_runner(proj, session, config) -> PipelineRunner:
    chroma = _chromadb.PersistentClient(path=str(config.chroma_path))
    return PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=ChromaVectorStore(chroma, f"project_{proj.id}"),
        embedder=SentenceTransformerEmbedder(config.inference.embedding_model),
        chunker=TextChunker(min_words=proj.chunk_min_size, max_words=proj.chunk_max_size),
    )


@router.post("/run/stream")
def run_pipeline_stream(
    project_id: str,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    proj = _get_project_or_404(project_id, session)
    config = get_config()
    runner = _make_runner(proj, session, config)

    def event_stream() -> Generator[str, None, None]:
        total = 0
        for phase_name, phase_fn in [
            ("chunk", runner._chunk),
            ("embed", runner._embed),
            ("cluster", runner._cluster),
        ]:
            yield f"data: {json.dumps({'phase': phase_name, 'status': 'running'})}\n\n"
            try:
                phase_result = phase_fn(proj.id)
                session.commit()
                total += phase_result.items_processed
                yield f"data: {json.dumps({'phase': phase_name, 'status': 'done', 'items_processed': phase_result.items_processed})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'phase': phase_name, 'status': 'error', 'error': str(exc)})}\n\n"
                return
        yield f"data: {json.dumps({'complete': True, 'total_processed': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
