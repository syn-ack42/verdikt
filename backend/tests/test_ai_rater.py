from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from verdikt.core.models import Chunk, DimensionProfile, Domain, PreferenceProfile, Project, Rating, RatingDimension
from verdikt.inference.ai_rater import AIRater
from verdikt.inference.judge import LLMJudge


def _make_project() -> Project:
    return Project(
        name="Test",
        rating_dimensions=[RatingDimension(name="Prose", description="Writing", weight=1.0)],
    )


def _make_profile(project: Project) -> PreferenceProfile:
    return PreferenceProfile(
        project_id=project.id,
        overall_summary="Prefers literary prose.",
        dimensions=[DimensionProfile(name="Prose", description="Writing", summary="Good prose.", typical_score=3.5)],
        rating_count=10,
    )


def _make_chunk(chunk_id: str, material_id: str = "m1", content: str = "Some text.") -> Chunk:
    return Chunk(
        id=chunk_id,
        material_item_id=material_id,
        project_id="proj",
        content=content,
        position=0,
        size=10,
        cluster_id=1,
    )


def _make_stores(chunks: list[Chunk], ratings: list[Rating], ai_ratings: list[Rating] = None):
    """Build mocked store objects."""
    chunk_store = MagicMock()
    chunk_store.list_by_project.return_value = chunks
    chunk_store.list_ids_by_project.return_value = [(c.id, c.material_item_id) for c in chunks]
    chunk_store.get.side_effect = lambda cid: next((c for c in chunks if c.id == cid), None)
    chunk_store.get_by_ids.side_effect = lambda ids: [c for c in chunks if c.id in ids]

    all_ratings = ratings + (ai_ratings or [])
    rating_store = MagicMock()
    rating_store.list_unconfirmed_ai.return_value = ai_ratings or []
    rating_store.get_all_rated_chunk_ids.return_value = {r.chunk_id for r in all_ratings}
    rating_store.save = MagicMock()
    rating_store.update_ai_scores = MagicMock()

    mat_store = MagicMock()
    vector_store = MagicMock()
    vector_store.query.return_value = [{"id": c.id} for c in chunks]

    embedder = MagicMock()
    embedder.embed.return_value = [[0.0] * 384]

    return chunk_store, rating_store, mat_store, vector_store, embedder


def _make_judge(score: float = 4.0) -> LLMJudge:
    judge = MagicMock(spec=LLMJudge)
    judge.score_chunk.return_value = ({"Prose": score}, score, {}, None)
    return judge


def _collect_events(rater, project, profile, **kwargs) -> list[dict]:
    stop_flag: list = []
    return list(rater.run(project=project, profile=profile, stop_flag=stop_flag, **kwargs))


def test_rated_chunks_excluded():
    project = _make_project()
    profile = _make_profile(project)
    chunks = [_make_chunk("c1"), _make_chunk("c2"), _make_chunk("c3")]
    existing = [Rating(project_id="proj", chunk_id="c1", material_item_id="m1", dimension_scores={"Prose": 3.0})]

    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, existing)
    # c1 is already rated → get_all_rated_chunk_ids returns {"c1"}
    rating_store.get_all_rated_chunk_ids.return_value = {"c1"}

    rater = AIRater(vs, emb, _make_judge(), chunk_store, rating_store, mat_store)
    events = _collect_events(rater, project, profile, batch_size=10)

    saved_ids = [call.args[0].chunk_id for call in rating_store.save.call_args_list]
    assert "c1" not in saved_ids
    assert "c2" in saved_ids or "c3" in saved_ids


def test_rescore_unconfirmed_runs_first():
    project = _make_project()
    profile = _make_profile(project)
    chunks = [_make_chunk("c1"), _make_chunk("c2")]
    ai_rating = Rating(project_id="proj", chunk_id="c1", material_item_id="m1", dimension_scores={"Prose": 3.0}, is_ai=True)

    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [], [ai_rating])
    rating_store.get_all_rated_chunk_ids.return_value = {"c1"}

    judge = _make_judge(4.5)
    rater = AIRater(vs, emb, judge, chunk_store, rating_store, mat_store)
    events = _collect_events(rater, project, profile, batch_size=5)

    event_types = [e["type"] for e in events]
    assert event_types[0] == "start"
    assert "rescore" in event_types
    rescore_idx = event_types.index("rescore")
    # rescore events must come before any progress events
    progress_indices = [i for i, t in enumerate(event_types) if t == "progress"]
    if progress_indices:
        assert rescore_idx < progress_indices[0]

    rating_store.update_ai_scores.assert_called_once_with(ai_rating.id, {"Prose": 4.5})


def test_stop_condition_triggers_after_declining_batches():
    project = _make_project()
    profile = _make_profile(project)
    # 30 chunks → 3 batches of 10
    chunks = [_make_chunk(f"c{i}") for i in range(30)]
    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [])
    rating_store.get_all_rated_chunk_ids.return_value = set()
    vs.query.return_value = [{"id": c.id} for c in chunks]

    # Scores decline: 4.0, 3.0, 2.0 → window=3, threshold=2.5 → should stop after 3rd batch
    call_count = 0
    scores_seq = [4.0, 3.0, 2.0]

    def _score(content, profile, project):
        nonlocal call_count
        batch_idx = call_count // 10
        s = scores_seq[min(batch_idx, len(scores_seq) - 1)]
        call_count += 1
        return ({"Prose": s}, s, {}, None)

    judge = MagicMock(spec=LLMJudge)
    judge.score_chunk.side_effect = _score

    rater = AIRater(vs, emb, judge, chunk_store, rating_store, mat_store)
    events = _collect_events(rater, project, profile, batch_size=10, stop_window=3, stop_threshold=2.5)

    final = events[-1]
    assert final["type"] == "stopped"
    assert final["reason"] == "diminishing_returns"


def test_stop_condition_not_triggered_on_single_dip():
    project = _make_project()
    profile = _make_profile(project)
    # Only 2 batches — not enough for stop_window=3
    chunks = [_make_chunk(f"c{i}") for i in range(20)]
    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [])
    rating_store.get_all_rated_chunk_ids.return_value = set()
    vs.query.return_value = [{"id": c.id} for c in chunks]

    judge = _make_judge(1.5)  # low score, but only 2 batches
    rater = AIRater(vs, emb, judge, chunk_store, rating_store, mat_store)
    events = _collect_events(rater, project, profile, batch_size=10, stop_window=3, stop_threshold=2.5)

    final = events[-1]
    # Should complete (pool exhausted), not stop due to declining
    assert final["type"] == "complete"


def test_complete_event_when_pool_exhausted():
    project = _make_project()
    profile = _make_profile(project)
    chunks = [_make_chunk("c1")]
    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [])
    rating_store.get_all_rated_chunk_ids.return_value = set()
    vs.query.return_value = [{"id": "c1"}]

    rater = AIRater(vs, emb, _make_judge(), chunk_store, rating_store, mat_store)
    events = _collect_events(rater, project, profile, batch_size=10)

    assert events[-1]["type"] == "complete"


def test_user_stop_respected():
    project = _make_project()
    profile = _make_profile(project)
    chunks = [_make_chunk(f"c{i}") for i in range(100)]
    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [])
    rating_store.get_all_rated_chunk_ids.return_value = set()
    vs.query.return_value = [{"id": c.id} for c in chunks]

    stop_flag: list = []
    call_count = [0]
    orig_score = _make_judge().score_chunk

    judge = MagicMock(spec=LLMJudge)

    def _score(content, profile, project):
        call_count[0] += 1
        if call_count[0] >= 5:
            stop_flag.append(True)
        return ({"Prose": 4.0}, 4.0, {}, None)

    judge.score_chunk.side_effect = _score

    rater = AIRater(vs, emb, judge, chunk_store, rating_store, mat_store)
    events = list(rater.run(project=project, profile=profile, stop_flag=stop_flag, batch_size=20))

    final = events[-1]
    assert final["type"] == "stopped"
    assert final["reason"] == "user_stopped"


# ── image domain ──────────────────────────────────────────────────────────────

def _make_image_project() -> Project:
    return Project(
        name="Images",
        domain=Domain.IMAGE,
        rating_dimensions=[RatingDimension(name="Composition", description="Balance", weight=1.0)],
    )


def _make_image_profile(project: Project) -> PreferenceProfile:
    return PreferenceProfile(
        project_id=project.id,
        overall_summary="Prefers balanced compositions.",
        dimensions=[DimensionProfile(name="Composition", description="Balance", summary="Good.", typical_score=4.0)],
        rating_count=10,
    )


def test_image_project_skips_text_embedding():
    """For image projects the embedder must not be called (CLIP rejects text)."""
    project = _make_image_project()
    profile = _make_image_profile(project)
    chunks = [
        Chunk(id="img1", material_item_id="m1", project_id=project.id,
              content=b"\xff\xd8\xff", position=0, size=1),
    ]
    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [])
    rating_store.get_all_rated_chunk_ids.return_value = set()

    judge = MagicMock(spec=LLMJudge)
    judge.score_chunk.return_value = ({"Composition": 4.0}, 4.0, {}, None)

    rater = AIRater(vs, emb, judge, chunk_store, rating_store, mat_store)
    _collect_events(rater, project, profile, batch_size=10)

    emb.embed.assert_not_called()


def test_image_project_still_rates_chunks():
    """Image project AI rater must score chunks even without similarity ordering."""
    project = _make_image_project()
    profile = _make_image_profile(project)
    chunks = [
        Chunk(id=f"img{i}", material_item_id="m1", project_id=project.id,
              content=b"\xff\xd8\xff", position=i, size=1)
        for i in range(3)
    ]
    chunk_store, rating_store, mat_store, vs, emb = _make_stores(chunks, [])
    rating_store.get_all_rated_chunk_ids.return_value = set()

    judge = MagicMock(spec=LLMJudge)
    judge.score_chunk.return_value = ({"Composition": 3.5}, 3.5, {}, None)

    rater = AIRater(vs, emb, judge, chunk_store, rating_store, mat_store)
    _collect_events(rater, project, profile, batch_size=10)

    assert rating_store.save.call_count == 3
