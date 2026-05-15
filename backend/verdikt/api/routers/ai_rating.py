from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_engine, get_auth_session, get_cached_chroma_client, get_config, get_current_user, get_session
from verdikt.api.token_budget import check_token_budget, record_usage
from verdikt.core.user_models import AuthenticatedUser
from verdikt.inference.ai_rater import AIRater
from verdikt.inference.judge import LLMJudge
from verdikt.inference.resolver import resolve_embedder, resolve_llm_target
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.core.models import Rating
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteMaterialStore, SQLiteProfileStore,
    SQLiteProjectStore, SQLiteRatingStore,
)

"""AI background rating endpoints.

POST /start  — launch a background thread that scores unrated chunks with the LLM judge.
POST /stop   — signal the running thread to stop after the current chunk.
GET  /status — poll progress; includes profile_stale flag when a newer profile exists.
"""

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/ai-rating", tags=["ai-rating"])


def _dims_match(profile, proj) -> bool:
    """Return True if the profile's dimension names match the project's current dimensions."""
    profile_names = {d.name for d in profile.dimensions}
    project_names = {d.name for d in proj.rating_dimensions}
    return profile_names == project_names

# project_id → stop flag list (append any value to request stop)
_stop_flags: dict[str, list] = {}

# project_id → current status dict
_status: dict[str, dict] = {}

# per-project lock for the preview endpoint — non-blocking acquire prevents
# stacked concurrent Ollama calls when the user rates faster than the LLM responds
_preview_locks: dict[str, threading.Lock] = {}
_preview_locks_mutex = threading.Lock()


def _get_preview_lock(project_id: str) -> threading.Lock:
    with _preview_locks_mutex:
        if project_id not in _preview_locks:
            _preview_locks[project_id] = threading.Lock()
        return _preview_locks[project_id]


def _default_status() -> dict:
    return {
        "running": False,
        "profile_version": None,
        "profile_stale": False,
        "chunks_rated": 0,
        "batches_completed": 0,
        "last_batch_avg": None,
        "stopped_reason": None,
        "tokens_prompt": 0,
        "tokens_completion": 0,
    }


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


class StartRequest(BaseModel):
    batch_size: int = 20
    """Chunks scored per batch (default 20)."""
    random_fraction: float = 0.2
    """Fraction of each batch filled randomly rather than by similarity order (default 0.2)."""


@router.post("/start", status_code=202)
def start_ai_rating(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    body: StartRequest = StartRequest(),
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    check_token_budget(user.id, auth_session)
    proj = _get_project_or_404(project_id, session)

    if project_id in _stop_flags:
        raise HTTPException(status_code=409, detail="AI rating already running for this project")

    profile = SQLiteProfileStore(session).get_latest(project_id)
    if profile is None:
        raise HTTPException(status_code=503, detail="No crystallised profile found. Crystallise first.")
    if not _dims_match(profile, proj):
        raise HTTPException(status_code=409, detail="Profile dimensions don't match project dimensions. Re-crystallise first.")

    config = get_config()
    target = resolve_llm_target(proj, config, auth_session, user_id=user.id)
    chroma = get_cached_chroma_client(user.id)
    vector_store = ChromaVectorStore(chroma, f"project_{project_id}")
    embedder = resolve_embedder(proj, config, auth_session, user_id=user.id)
    judge = LLMJudge(target, timeout=config.inference.ollama_timeout)

    # Take copies for the thread (session is not thread-safe; import lazily for testability)
    from sqlalchemy.orm import Session as _Session
    from verdikt.api.deps import get_user_engine
    engine = get_user_engine(user)

    stop_flag: list = []
    _stop_flags[project_id] = stop_flag
    _status[project_id] = {
        **_default_status(),
        "running": True,
        "profile_version": profile.version,
    }

    user_id_capture = user.id

    def _run() -> None:
        with _Session(engine) as thread_session:
            rating_store = SQLiteRatingStore(thread_session)
            chunk_store = SQLiteChunkStore(thread_session)
            mat_store = SQLiteMaterialStore(thread_session)
            profile_store = SQLiteProfileStore(thread_session)

            rater = AIRater(
                vector_store=vector_store,
                embedder=embedder,
                judge=judge,
                chunk_store=chunk_store,
                rating_store=rating_store,
                material_store=mat_store,
            )

            try:
                for event in rater.run(
                    project=proj,
                    profile=profile,
                    stop_flag=stop_flag,
                    batch_size=body.batch_size,
                    random_fraction=body.random_fraction,
                ):
                    etype = event.get("type")
                    if etype == "progress":
                        _status[project_id]["chunks_rated"] = (
                            _status[project_id].get("chunks_rated", 0) + 1
                        )
                        if judge.usage:
                            _status[project_id]["tokens_prompt"] = sum(p for p, _ in judge.usage)
                            _status[project_id]["tokens_completion"] = sum(c for _, c in judge.usage)
                    elif etype == "batch_done":
                        _status[project_id]["batches_completed"] = event.get("batch", 0)
                        _status[project_id]["last_batch_avg"] = event.get("avg")
                        _status[project_id]["chunks_rated"] = event.get("total_rated", 0)
                        if judge.usage:
                            _status[project_id]["tokens_prompt"] = sum(p for p, _ in judge.usage)
                            _status[project_id]["tokens_completion"] = sum(c for _, c in judge.usage)
                    elif etype in ("stopped", "complete"):
                        _status[project_id]["stopped_reason"] = event.get("reason") or ("complete" if etype == "complete" else None)
                        _status[project_id]["chunks_rated"] = event.get("total_rated", _status[project_id].get("chunks_rated", 0))
                        if judge.usage:
                            _status[project_id]["tokens_prompt"] = sum(p for p, _ in judge.usage)
                            _status[project_id]["tokens_completion"] = sum(c for _, c in judge.usage)
                    elif etype == "rescore":
                        pass  # progress shown via status polling

                    # Commit after each save
                    try:
                        thread_session.commit()
                    except Exception:
                        thread_session.rollback()

                # Check profile staleness
                latest = profile_store.get_latest(project_id)
                if latest and latest.version != profile.version:
                    _status[project_id]["profile_stale"] = True

            except Exception:
                log.exception("ai_rater thread error for project %s", project_id)
                _status[project_id]["stopped_reason"] = "error"
            finally:
                _status[project_id]["running"] = False
                _stop_flags.pop(project_id, None)

            # Flush token usage accumulated during run
            if judge.usage:
                total_prompt = sum(p for p, _ in judge.usage)
                total_completion = sum(c for _, c in judge.usage)
                try:
                    with _Session(get_auth_engine()) as auth_sess:
                        record_usage(user_id_capture, project_id, target.model, "ai_rating",
                                     total_prompt, total_completion, auth_sess)
                except Exception:
                    log.warning("ai_rater: failed to record token usage")

    thread = threading.Thread(target=_run, daemon=True, name=f"ai-rater-{project_id}")
    thread.start()

    return {"status": "started"}


@router.post("/stop")
def stop_ai_rating(
    project_id: str,
    _: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    flag = _stop_flags.get(project_id)
    if flag is not None:
        flag.append(True)
    if project_id in _status:
        # Mark as not running immediately so the UI reflects the stop without
        # waiting for the current LLM call to finish.
        _status[project_id]["running"] = False
        _status[project_id]["stopped_reason"] = "user_stopped"
    return {"status": "stopped"}


class AiPreviewRequest(BaseModel):
    chunk_id: str
    material_item_id: str


@router.post("/preview", status_code=201)
def ai_preview_rating(
    project_id: str,
    body: AiPreviewRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    """Rate a single chunk synchronously against the current profile (for background eager preview)."""
    check_token_budget(user.id, auth_session)
    proj = _get_project_or_404(project_id, session)

    rating_store = SQLiteRatingStore(session)
    if body.chunk_id in rating_store.get_all_rated_chunk_ids(project_id):
        raise HTTPException(status_code=409, detail="already_rated")

    profile = SQLiteProfileStore(session).get_latest(project_id)
    if profile is None:
        raise HTTPException(status_code=503, detail="No profile found")
    if not _dims_match(profile, proj):
        raise HTTPException(status_code=409, detail="Profile dimensions don't match project dimensions. Re-crystallise first.")

    chunk = SQLiteChunkStore(session).get(body.chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    config = get_config()
    target = resolve_llm_target(proj, config, auth_session, user_id=user.id)
    judge = LLMJudge(target, timeout=config.inference.ollama_timeout)

    lock = _get_preview_lock(project_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="preview_busy")

    chunk_store = SQLiteChunkStore(session)
    try:
        scores, _, explanations, description = judge.score_chunk(chunk.content, profile, proj)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI rating failed: {exc}")
    finally:
        lock.release()

    if judge.usage:
        p, c = judge.usage[-1]
        record_usage(user.id, project_id, target.model, "preview", p, c, auth_session)

    rating = Rating(
        project_id=project_id,
        chunk_id=body.chunk_id,
        material_item_id=body.material_item_id,
        dimension_scores=scores,
        is_ai=True,
        explanations=explanations,
    )
    rating_store.save(rating)
    if description:
        chunk_store.update_description(body.chunk_id, description)
    session.commit()

    return {
        "ai_rating_id": rating.id,
        "dimension_scores": scores,
        "explanations": explanations,
    }


@router.post("/rate-chunk", status_code=201)
def rate_chunk_ai(
    project_id: str,
    body: AiPreviewRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    """Rate a single chunk with AI, replacing any existing AI rating. Used for explicit user-triggered (re-)rating."""
    check_token_budget(user.id, auth_session)
    proj = _get_project_or_404(project_id, session)

    profile = SQLiteProfileStore(session).get_latest(project_id)
    if profile is None:
        raise HTTPException(status_code=503, detail="No profile found")
    if not _dims_match(profile, proj):
        raise HTTPException(status_code=409, detail="Profile dimensions don't match project dimensions. Re-crystallise first.")

    chunk = SQLiteChunkStore(session).get(body.chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    config = get_config()
    target = resolve_llm_target(proj, config, auth_session, user_id=user.id)
    judge = LLMJudge(target, timeout=config.inference.ollama_timeout)

    chunk_store = SQLiteChunkStore(session)
    rating_store = SQLiteRatingStore(session)

    try:
        scores, _, explanations, description = judge.score_chunk(chunk.content, profile, proj)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI rating failed: {exc}")

    if judge.usage:
        p, c = judge.usage[-1]
        record_usage(user.id, project_id, target.model, "rate_chunk", p, c, auth_session)

    # Delete any existing AI rating for this chunk before saving a new one
    existing = [r for r in rating_store.list_by_project(project_id)
                if r.chunk_id == body.chunk_id and r.is_ai and not r.skipped]
    for old in existing:
        rating_store.delete(old.id)

    rating = Rating(
        project_id=project_id,
        chunk_id=body.chunk_id,
        material_item_id=body.material_item_id,
        dimension_scores=scores,
        is_ai=True,
        explanations=explanations,
    )
    rating_store.save(rating)
    if description:
        chunk_store.update_description(body.chunk_id, description)
    session.commit()

    return {
        "ai_rating_id": rating.id,
        "dimension_scores": scores,
        "explanations": explanations,
    }


@router.get("/status")
def get_ai_rating_status(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    state = dict(_status.get(project_id, _default_status()))

    profile_store = SQLiteProfileStore(session)
    latest = profile_store.get_latest(project_id)

    # Check version staleness
    if state.get("profile_version") is not None and not state.get("running"):
        if latest and latest.version != state["profile_version"]:
            state["profile_stale"] = True

    # Check dimension mismatch even when no run is in progress
    if latest and not _dims_match(latest, proj):
        state["profile_stale"] = True

    state["unconfirmed_ai_count"] = len(SQLiteRatingStore(session).list_unconfirmed_ai(project_id))

    return state
