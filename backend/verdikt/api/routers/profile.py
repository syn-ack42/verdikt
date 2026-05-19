from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Annotated, AsyncGenerator
from uuid import uuid4

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_engine, get_auth_session, get_config, get_current_user, get_session, get_user_engine
from verdikt.api.token_budget import check_token_budget, record_usage
from verdikt.core.user_models import AuthenticatedUser
from verdikt.core.models import DimensionProfile, PreferenceProfile
from verdikt.inference.crystalliser import ProfileCrystalliser
from verdikt.inference.prompts import load_prompts
from verdikt.inference.resolver import resolve_llm_target
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteProfileStore, SQLiteProjectStore, SQLiteRatingStore,
)

router = APIRouter(prefix="/api/projects/{project_id}/profile", tags=["profile"])

# In-memory status for currently-crystallising projects (single-process only)
_crystallise_status: dict[str, dict] = {}


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _profile_response(p: PreferenceProfile) -> dict:
    profile_confidence = (
        round(p.score_sum / p.confirmed_count, 4) if p.confirmed_count > 0 else None
    )
    return {
        "id": p.id,
        "project_id": p.project_id,
        "version": p.version,
        "dimensions": [d.model_dump() for d in p.dimensions],
        "overall_summary": p.overall_summary,
        "rating_count": p.rating_count,
        "confirmed_count": p.confirmed_count,
        "score_sum": p.score_sum,
        "profile_confidence": profile_confidence,
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
def get_profile(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    profile = SQLiteProfileStore(session).get_latest(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile found")
    return _profile_response(profile)


@router.get("/versions")
def list_profile_versions(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    _get_project_or_404(project_id, session)
    return [_profile_response(p) for p in SQLiteProfileStore(session).list_versions(project_id)]


@router.get("/crystallise/status")
def crystallise_status(
    project_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict:
    st = _crystallise_status.get(project_id)
    if st is None:
        return {"running": False, "tokens_prompt": 0, "tokens_completion": 0}
    return dict(st)


@router.post("/crystallise", status_code=201)
def crystallise_profile(
    project_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    check_token_budget(user.id, auth_session)
    proj = _get_project_or_404(project_id, session)
    rating_store = SQLiteRatingStore(session)
    chunk_store = SQLiteChunkStore(session)
    profile_store = SQLiteProfileStore(session)

    ratings = rating_store.list_by_project(project_id)
    non_skipped = [r for r in ratings if not r.skipped]

    if len(non_skipped) < proj.crystallisation_threshold:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Need {proj.crystallisation_threshold} ratings to crystallise, "
                f"have {len(non_skipped)}."
            ),
        )

    chunks_by_id = {c.id: c for c in chunk_store.list_by_project(project_id)}
    current = profile_store.get_latest(project_id)
    current_version = current.version if current else 0

    config = get_config()
    target = resolve_llm_target(proj, config, auth_session, user_id=user.id)
    crystalliser = ProfileCrystalliser(target, prompts=load_prompts(auth_session))
    _crystallise_status[project_id] = {"running": True, "tokens_prompt": 0, "tokens_completion": 0}
    log.info("crystallise: starting for project %s (user=%s, model=%s, ratings=%d)",
             project_id, user.id, target.model, len(non_skipped))

    def _on_tokens(p: int, c: int) -> None:
        if project_id in _crystallise_status:
            _crystallise_status[project_id]["tokens_prompt"] = p
            _crystallise_status[project_id]["tokens_completion"] = c

    try:
        profile, prompt_tokens, completion_tokens = crystalliser.crystallise(
            project=proj,
            ratings=ratings,
            chunks_by_id=chunks_by_id,
            current_version=current_version,
            on_tokens=_on_tokens,
        )
    except Exception as exc:
        import httpx as _httpx
        if isinstance(exc, _httpx.ConnectError):
            log.warning("crystallise: cannot reach LLM at %s (project=%s)", target.base_url, project_id)
            raise HTTPException(
                status_code=503,
                detail=f"Cannot reach LLM at {target.base_url}. Is it running?",
            )
        if isinstance(exc, _httpx.HTTPStatusError):
            log.warning("crystallise: LLM returned %s for project %s: %s",
                        exc.response.status_code, project_id, exc.response.text[:200])
            raise HTTPException(status_code=502, detail=f"LLM error: {exc.response.text[:200]}")
        log.exception("crystallise: unexpected error for project %s", project_id)
        raise HTTPException(status_code=500, detail=f"Crystallisation failed: {exc}")
    finally:
        _crystallise_status.pop(project_id, None)

    log.info("crystallise: done for project %s version=%d tokens=%d+%d",
             project_id, profile.version, prompt_tokens, completion_tokens)
    record_usage(user.id, project_id, target.model, "crystallise", prompt_tokens, completion_tokens, auth_session)
    profile_store.save(profile)
    session.commit()
    return _profile_response(profile)


@router.post("/crystallise/stream")
async def crystallise_stream(
    project_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
):
    check_token_budget(user.id, auth_session)
    proj = _get_project_or_404(project_id, session)
    rating_store = SQLiteRatingStore(session)
    chunk_store = SQLiteChunkStore(session)
    profile_store = SQLiteProfileStore(session)

    ratings = rating_store.list_by_project(project_id)
    non_skipped = [r for r in ratings if not r.skipped]

    if len(non_skipped) < proj.crystallisation_threshold:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Need {proj.crystallisation_threshold} ratings to crystallise, "
                f"have {len(non_skipped)}."
            ),
        )

    chunks_by_id = {c.id: c for c in chunk_store.list_by_project(project_id)}
    current = profile_store.get_latest(project_id)
    current_version = current.version if current else 0

    config = get_config()
    target = resolve_llm_target(proj, config, auth_session, user_id=user.id)
    crystalliser = ProfileCrystalliser(target, prompts=load_prompts(auth_session))

    _user = user
    _user_id = user.id
    _project_id = project_id
    _target = target

    _crystallise_status[_project_id] = {"running": True, "tokens_prompt": 0, "tokens_completion": 0}

    async def event_stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()

        def on_tokens(p: int, c: int) -> None:
            if _project_id in _crystallise_status:
                _crystallise_status[_project_id]["tokens_prompt"] = p
                _crystallise_status[_project_id]["tokens_completion"] = c
            queue.put_nowait({"type": "progress", "prompt": p, "completion": c})

        def run() -> None:
            log.info("crystallise stream: starting for project %s (user=%s, model=%s, ratings=%d)",
                     _project_id, _user_id, _target.model, len(non_skipped))
            try:
                profile, pt, ct = crystalliser.crystallise(
                    project=proj,
                    ratings=ratings,
                    chunks_by_id=chunks_by_id,
                    current_version=current_version,
                    on_tokens=on_tokens,
                )
                log.info("crystallise stream: done for project %s version=%d tokens=%d+%d",
                         _project_id, profile.version, pt, ct)

                # Save in the thread — the event_stream generator may be cancelled if
                # the client disconnected before we finish, so we cannot rely on saving
                # from the async generator.
                try:
                    from sqlalchemy.orm import Session as _Session
                    engine = get_user_engine(_user)
                    with _Session(engine) as db_session:
                        SQLiteProfileStore(db_session).save(profile)
                        db_session.commit()
                    log.info("crystallise stream: profile v%d committed to DB (project=%s id=%s)",
                             profile.version, _project_id, profile.id)
                except Exception:
                    log.exception("crystallise stream: failed to persist profile for project %s", _project_id)

                try:
                    with Session(get_auth_engine()) as auth_sess:
                        record_usage(_user_id, _project_id, _target.model, "crystallise", pt, ct, auth_sess)
                except Exception:
                    log.warning("crystallise stream: failed to record token usage for project %s", _project_id)

                queue.put_nowait({
                    "type": "done",
                    "profile": _profile_response(profile),
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                })
            except Exception as exc:
                import httpx as _httpx
                if isinstance(exc, _httpx.ConnectError):
                    msg = f"Cannot reach LLM at {_target.base_url}. Is it running?"
                    log.warning("crystallise stream: cannot reach LLM at %s (project=%s)", _target.base_url, _project_id)
                elif isinstance(exc, _httpx.HTTPStatusError):
                    msg = f"LLM error: {exc.response.text[:200]}"
                    log.warning("crystallise stream: LLM returned %s for project %s: %s",
                                exc.response.status_code, _project_id, exc.response.text[:200])
                else:
                    msg = str(exc) or "Crystallisation failed"
                    log.exception("crystallise stream: unexpected error for project %s", _project_id)
                queue.put_nowait({"type": "error", "message": msg})
            finally:
                _crystallise_status.pop(_project_id, None)

        thread = threading.Thread(target=run, daemon=True, name=f"crystallise-{_project_id}")
        thread.start()

        while True:
            item = await queue.get()
            yield f"data: {json.dumps(item)}\n\n"
            if item["type"] in ("done", "error"):
                break
        thread.join(timeout=5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class ProfileUpdate(BaseModel):
    overall_summary: str | None = None
    dimensions: list[dict] | None = None


@router.put("")
def update_profile(
    project_id: str,
    body: ProfileUpdate,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    profile_store = SQLiteProfileStore(session)
    current = profile_store.get_latest(project_id)
    if current is None:
        raise HTTPException(status_code=404, detail="No profile found")

    new_profile = PreferenceProfile(
        id=str(uuid4()),
        project_id=project_id,
        version=current.version + 1,
        dimensions=[DimensionProfile(**d) for d in body.dimensions] if body.dimensions is not None else current.dimensions,
        overall_summary=body.overall_summary if body.overall_summary is not None else current.overall_summary,
        rating_count=current.rating_count,
        created_at=datetime.now(timezone.utc),
    )
    profile_store.save(new_profile)
    session.commit()
    return _profile_response(new_profile)


@router.post("/versions/{version_id}/restore", status_code=201)
def restore_profile_version(
    project_id: str,
    version_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    profile_store = SQLiteProfileStore(session)

    versions = profile_store.list_versions(project_id)
    target = next((v for v in versions if v.id == version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Version not found")

    current = profile_store.get_latest(project_id)
    new_version = (current.version if current else 0) + 1

    restored = PreferenceProfile(
        id=str(uuid4()),
        project_id=project_id,
        version=new_version,
        dimensions=target.dimensions,
        overall_summary=target.overall_summary,
        rating_count=target.rating_count,
        created_at=datetime.now(timezone.utc),
    )
    profile_store.save(restored)
    session.commit()
    return _profile_response(restored)
