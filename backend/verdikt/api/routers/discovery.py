from __future__ import annotations

import base64
import json
import logging
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update as _sql_update
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_engine, get_auth_session, get_config, get_current_user, get_session
from verdikt.api.token_budget import check_token_budget, record_usage
from verdikt.core.models import DiscoveryRating, RatingDimension
from verdikt.core.user_models import AuthenticatedUser
from verdikt.inference.dimension_discoverer import DimensionDiscoverer
from verdikt.inference.resolver import resolve_llm_model
from verdikt.pipeline.selector import RatingSelector
from verdikt.storage.orm import ProjectRow
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteDiscoveryRatingStore, SQLiteMaterialStore, SQLiteProjectStore, SQLiteRatingStore,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/discovery", tags=["discovery"])

_READY_LIKED = 5
_READY_DISLIKED = 5

# project_id → analysis status dict (in-memory, same pattern as ai_rating)
_analysis_status: dict[str, dict] = {}
# project_id → stop flag list
_stop_flags: dict[str, list] = {}


def _default_analysis_status() -> dict:
    return {
        "running": False,
        "phase": None,        # "describing" | "synthesising" | None
        "done": 0,
        "total": 0,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "result": None,       # DiscoveryAnalysisResult.model_dump() when complete
        "error": None,
    }


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.get("/next")
def discovery_next(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Return the next chunk for discovery rating using cluster-diversity sampling."""
    proj = _get_project_or_404(project_id, session)
    chunk_store = SQLiteChunkStore(session)
    discovery_store = SQLiteDiscoveryRatingStore(session)
    mat_store = SQLiteMaterialStore(session)

    already_rated = discovery_store.get_rated_chunk_ids(project_id)

    class _ProxyRatingStore:
        def get_human_rated_chunk_ids(self, pid: str) -> set[str]:
            return already_rated

        def get_complete_human_rated_chunk_ids(self, pid: str, dim_names: set[str]) -> set[str]:
            return already_rated

        def count_by_project(self, pid: str) -> int:
            return len(already_rated)

        def list_unconfirmed_ai(self, pid: str):
            return []

        def list_human_scores(self, pid: str) -> dict:
            return {}

    selector = RatingSelector(chunk_store, _ProxyRatingStore(), project=proj)  # type: ignore[arg-type]
    chunk = selector._next_diversity(project_id)  # noqa: SLF001

    if chunk is None:
        raise HTTPException(status_code=404, detail="no_chunks_available")

    material_item = mat_store.get(chunk.material_item_id)
    counts = discovery_store.counts(project_id)

    if isinstance(chunk.content, bytes):
        chunk_content = base64.b64encode(chunk.content).decode()
        chunk_domain = "image"
    else:
        chunk_content = chunk.content
        chunk_domain = "text"

    return {
        "chunk": {
            "id": chunk.id,
            "content": chunk_content,
            "domain": chunk_domain,
            "position": chunk.position,
            "cluster_id": chunk.cluster_id,
            "description": chunk.description,
        },
        "material_item": {
            "id": material_item.id if material_item else None,
            "work_title": material_item.work_title if material_item else None,
            "author": material_item.author if material_item else None,
            "source_path": material_item.source_path if material_item else None,
            "project_seq": material_item.project_seq if material_item else None,
        },
        "total_discovery_rated": counts["total"],
        "liked": counts["liked"],
        "disliked": counts["disliked"],
    }


class DiscoveryRatingSubmit(BaseModel):
    chunk_id: str
    material_item_id: str
    preference: float   # -2 to +2; 0 treated as skip/neutral
    reason: str | None = None


@router.post("/ratings", status_code=201)
def submit_discovery_rating(
    project_id: str,
    body: DiscoveryRatingSubmit,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    store = SQLiteDiscoveryRatingStore(session)
    dr = DiscoveryRating(
        project_id=project_id,
        chunk_id=body.chunk_id,
        material_item_id=body.material_item_id,
        preference=max(-2.0, min(2.0, body.preference)),
        reason=body.reason or None,
    )
    store.save(dr)
    session.commit()
    counts = store.counts(project_id)
    return {
        "ok": True,
        "total": counts["total"],
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "ready": counts["liked"] >= _READY_LIKED and counts["disliked"] >= _READY_DISLIKED,
    }


@router.get("/status")
def discovery_status(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    proj_row = session.get(ProjectRow, project_id)
    if proj_row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    counts = SQLiteDiscoveryRatingStore(session).counts(project_id)
    analysis = dict(_analysis_status.get(project_id, _default_analysis_status()))
    # If no in-memory result but a persisted result exists, surface it
    if analysis["result"] is None and proj_row.discovery_analysis_result:
        try:
            analysis["result"] = json.loads(proj_row.discovery_analysis_result)
        except Exception:
            pass
    return {
        "total": counts["total"],
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "ready": counts["liked"] >= _READY_LIKED and counts["disliked"] >= _READY_DISLIKED,
        "analysis": analysis,
    }


@router.post("/analyse/start", status_code=202)
def start_analysis(
    project_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    """Launch analysis in a background thread. Returns 202 immediately."""
    check_token_budget(user.id, auth_session)

    if project_id in _stop_flags:
        raise HTTPException(status_code=409, detail="Analysis already running for this project")

    proj = _get_project_or_404(project_id, session)
    discovery_store = SQLiteDiscoveryRatingStore(session)
    chunk_store = SQLiteChunkStore(session)

    discovery_ratings = discovery_store.list_by_project(project_id)
    active = [dr for dr in discovery_ratings if abs(dr.preference) >= 0.5]
    if not active:
        raise HTTPException(status_code=422, detail="No non-neutral discovery ratings found")

    chunk_ids = {dr.chunk_id for dr in active}
    chunks_by_id = {c.id: c for c in chunk_store.list_by_project(project_id) if c.id in chunk_ids}

    config = get_config()
    ollama_base_url, llm_model = resolve_llm_model(proj, config)

    from verdikt.api.deps import get_user_engine
    from sqlalchemy.orm import Session as _Session
    engine = get_user_engine(user)

    stop_flag: list = []
    _stop_flags[project_id] = stop_flag
    _analysis_status[project_id] = {
        **_default_analysis_status(),
        "running": True,
        "phase": "describing",
        "total": len(active),
    }

    _project = proj
    _ratings = active
    _chunks = chunks_by_id
    _user_id = user.id
    _model = llm_model

    def _run() -> None:
        discoverer = DimensionDiscoverer(model=_model, base_url=ollama_base_url)
        prompt_tokens = 0
        completion_tokens = 0
        descriptions: list[tuple[float, str]] = []

        try:
            for i, dr in enumerate(_ratings):
                if stop_flag:
                    _analysis_status[project_id]["error"] = "Cancelled"
                    return

                chunk = _chunks.get(dr.chunk_id)
                if chunk is None:
                    continue
                try:
                    qualities, pt, ct = discoverer._describe_chunk(chunk, dr, _project.domain)  # noqa: SLF001
                    prompt_tokens += pt
                    completion_tokens += ct
                    if qualities:
                        descriptions.append((dr.preference, qualities))
                except Exception:
                    pass

                _analysis_status[project_id].update({
                    "done": i + 1,
                    "tokens_prompt": prompt_tokens,
                    "tokens_completion": completion_tokens,
                })

            if stop_flag:
                _analysis_status[project_id]["error"] = "Cancelled"
                return

            _analysis_status[project_id].update({
                "phase": "synthesising",
                "done": 0,
                "total": 1,
            })

            result, pt, ct = discoverer._extract_dimensions(descriptions, _project)  # noqa: SLF001
            prompt_tokens += pt
            completion_tokens += ct

            result_dict = result.model_dump()
            _analysis_status[project_id].update({
                "done": 1,
                "tokens_prompt": prompt_tokens,
                "tokens_completion": completion_tokens,
                "result": result_dict,
            })

            # Persist result to DB so it survives container restarts
            try:
                with _Session(engine) as user_sess:
                    user_sess.execute(
                        _sql_update(ProjectRow)
                        .where(ProjectRow.id == project_id)
                        .values(discovery_analysis_result=json.dumps(result_dict))
                    )
                    user_sess.commit()
            except Exception:
                log.warning("discovery: failed to persist analysis result for project %s", project_id)

            try:
                with _Session(get_auth_engine()) as auth_sess:
                    record_usage(_user_id, project_id, _model, "discovery_analyse",
                                 prompt_tokens, completion_tokens, auth_sess)
            except Exception:
                log.warning("discovery: failed to record token usage")

        except Exception as exc:
            log.exception("discovery analysis thread error for project %s", project_id)
            msg = str(exc) if str(exc) else "Analysis failed — see server logs"
            _analysis_status[project_id]["error"] = msg
        finally:
            _analysis_status[project_id]["running"] = False
            _stop_flags.pop(project_id, None)

    thread = threading.Thread(target=_run, daemon=True, name=f"discovery-{project_id}")
    thread.start()
    return {"status": "started"}


@router.post("/analyse/cancel")
def cancel_analysis(
    project_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict:
    flag = _stop_flags.get(project_id)
    if flag is not None:
        flag.append(True)
    if project_id in _analysis_status:
        _analysis_status[project_id]["running"] = False
    return {"ok": True}


@router.delete("/analyse/result")
def clear_analysis_result(
    project_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
) -> dict:
    """Discard the stored analysis result so a fresh analysis can be started."""
    _analysis_status.pop(project_id, None)
    session.execute(
        _sql_update(ProjectRow)
        .where(ProjectRow.id == project_id)
        .values(discovery_analysis_result=None)
    )
    session.commit()
    return {"ok": True}


class ApplyProposalBody(BaseModel):
    dimensions: list[dict]  # [{name, description, weight}]


@router.post("/apply")
def apply_proposal(
    project_id: str,
    body: ApplyProposalBody,
    session: Session = Depends(get_session),
) -> dict:
    """Apply the approved dimension proposal to the project."""
    proj = _get_project_or_404(project_id, session)

    new_dims = []
    for d in body.dimensions:
        name = str(d.get("name", "")).strip()
        desc = str(d.get("description", "")).strip()
        if not name:
            continue
        weight = float(d.get("weight", 1.0))
        weight = max(0.1, min(5.0, weight))
        new_dims.append(RatingDimension(name=name, description=desc, weight=weight))

    if not new_dims:
        raise HTTPException(status_code=422, detail="No valid dimensions in proposal")

    session.execute(
        _sql_update(ProjectRow)
        .where(ProjectRow.id == project_id)
        .values(rating_dimensions=json.dumps([d.model_dump() for d in new_dims]))
    )
    session.commit()

    proj.rating_dimensions = new_dims
    return {
        "id": proj.id,
        "name": proj.name,
        "rating_dimensions": [d.model_dump() for d in new_dims],
    }


@router.post("/reset")
def reset_discovery(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    SQLiteDiscoveryRatingStore(session).delete_by_project(project_id)
    # Clear analysis result from memory and DB
    _analysis_status.pop(project_id, None)
    _stop_flags.pop(project_id, None)
    session.execute(
        _sql_update(ProjectRow)
        .where(ProjectRow.id == project_id)
        .values(discovery_analysis_result=None)
    )
    session.commit()
    return {"ok": True}
