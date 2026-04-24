import pytest
from sqlalchemy.orm import Session

from verdikt.core.models import Rating
from verdikt.storage.sqlite import SQLiteRatingStore


@pytest.fixture
def store(session: Session) -> SQLiteRatingStore:
    return SQLiteRatingStore(session)


def _rating(project_id: str, chunk_id: str = "c1", material_item_id: str = "m1", **kw) -> Rating:
    return Rating(
        project_id=project_id,
        chunk_id=chunk_id,
        material_item_id=material_item_id,
        dimension_scores=kw.get("dimension_scores", {"Prose": 3.0}),
        skipped=kw.get("skipped", False),
        skip_reason=kw.get("skip_reason", None),
    )


def test_save_and_get(store: SQLiteRatingStore):
    r = _rating("proj1")
    store.save(r)
    fetched = store.get(r.id)
    assert fetched is not None
    assert fetched.id == r.id
    assert fetched.dimension_scores == {"Prose": 3.0}


def test_get_missing_returns_none(store: SQLiteRatingStore):
    assert store.get("nonexistent") is None


def test_list_by_project(store: SQLiteRatingStore):
    store.save(_rating("p1", chunk_id="c1"))
    store.save(_rating("p1", chunk_id="c2"))
    store.save(_rating("p2", chunk_id="c3"))
    assert len(store.list_by_project("p1")) == 2
    assert len(store.list_by_project("p2")) == 1


def test_list_by_chunk(store: SQLiteRatingStore):
    store.save(_rating("p1", chunk_id="c1"))
    store.save(_rating("p1", chunk_id="c1"))
    store.save(_rating("p1", chunk_id="c2"))
    assert len(store.list_by_chunk("c1")) == 2
    assert len(store.list_by_chunk("c2")) == 1


def test_count_by_project(store: SQLiteRatingStore):
    assert store.count_by_project("p1") == 0
    store.save(_rating("p1"))
    store.save(_rating("p1"))
    assert store.count_by_project("p1") == 2


def test_skip_round_trip(store: SQLiteRatingStore):
    r = _rating("p1", skipped=True, skip_reason="too short", dimension_scores={})
    store.save(r)
    fetched = store.get(r.id)
    assert fetched.skipped is True
    assert fetched.skip_reason == "too short"
    assert fetched.dimension_scores == {}


def test_is_ai_flag_default_false(store: SQLiteRatingStore):
    r = _rating("p1")
    store.save(r)
    fetched = store.get(r.id)
    assert fetched.is_ai is False


def test_is_ai_flag_true(store: SQLiteRatingStore):
    r = Rating(
        project_id="p1",
        chunk_id="c1",
        material_item_id="m1",
        dimension_scores={"Prose": 4.0},
        is_ai=True,
    )
    store.save(r)
    fetched = store.get(r.id)
    assert fetched.is_ai is True


def test_list_unconfirmed_ai(store: SQLiteRatingStore):
    store.save(Rating(project_id="p1", chunk_id="c1", material_item_id="m1", dimension_scores={"D": 4.0}, is_ai=True))
    store.save(Rating(project_id="p1", chunk_id="c2", material_item_id="m1", dimension_scores={"D": 2.0}, is_ai=True))
    store.save(Rating(project_id="p1", chunk_id="c3", material_item_id="m1", dimension_scores={"D": 3.0}, is_ai=False))
    result = store.list_unconfirmed_ai("p1")
    assert len(result) == 2
    # Ordered by avg score descending
    assert result[0].chunk_id == "c1"
    assert result[1].chunk_id == "c2"


def test_get_all_rated_chunk_ids(store: SQLiteRatingStore):
    store.save(_rating("p1", chunk_id="c1"))
    store.save(Rating(project_id="p1", chunk_id="c2", material_item_id="m1", dimension_scores={"D": 3.0}, is_ai=True))
    ids = store.get_all_rated_chunk_ids("p1")
    assert ids == {"c1", "c2"}


def test_count_by_type(store: SQLiteRatingStore):
    store.save(_rating("p1", chunk_id="c1"))
    store.save(Rating(project_id="p1", chunk_id="c2", material_item_id="m1", dimension_scores={"D": 3.0}, is_ai=True))
    store.save(Rating(project_id="p1", chunk_id="c3", material_item_id="m1", dimension_scores={"D": 3.0}, is_ai=True))
    counts = store.count_by_type("p1")
    assert counts["human"] == 1
    assert counts["ai"] == 2


def test_explanations_round_trip(store: SQLiteRatingStore):
    r = Rating(
        project_id="p1",
        chunk_id="c1",
        material_item_id="m1",
        dimension_scores={"D": 4.0},
        is_ai=True,
        explanations={"D": "Strong match on atmosphere."},
    )
    store.save(r)
    fetched = store.get(r.id)
    assert fetched.explanations == {"D": "Strong match on atmosphere."}


def test_explanations_defaults_to_empty(store: SQLiteRatingStore):
    r = Rating(project_id="p1", chunk_id="c1", material_item_id="m1", dimension_scores={"D": 3.0})
    store.save(r)
    fetched = store.get(r.id)
    assert fetched.explanations == {}


def test_update_scores_sets_is_ai_false(store: SQLiteRatingStore):
    r = Rating(
        project_id="p1",
        chunk_id="c1",
        material_item_id="m1",
        dimension_scores={"D": 4.0},
        is_ai=True,
    )
    store.save(r)
    store.update_scores(r.id, {"D": 3.0})
    fetched = store.get(r.id)
    assert fetched.is_ai is False
    assert fetched.dimension_scores == {"D": 3.0}
