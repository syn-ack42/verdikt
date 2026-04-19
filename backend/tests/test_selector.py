import pytest
from sqlalchemy.orm import Session

from verdikt.core.models import Chunk, Rating
from verdikt.pipeline.selector import RatingSelector
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteRatingStore


def _chunk(project_id: str, cluster_id: int | None, position: int = 0) -> Chunk:
    return Chunk(
        project_id=project_id,
        material_item_id="m1",
        content="some text",
        position=position,
        size=10,
        cluster_id=cluster_id,
    )


def _rating(project_id: str, chunk_id: str) -> Rating:
    return Rating(
        project_id=project_id,
        chunk_id=chunk_id,
        material_item_id="m1",
        dimension_scores={"Prose": 3.0},
    )


@pytest.fixture
def chunk_store(session: Session) -> SQLiteChunkStore:
    return SQLiteChunkStore(session)


@pytest.fixture
def rating_store(session: Session) -> SQLiteRatingStore:
    return SQLiteRatingStore(session)


def test_returns_none_when_no_clustered_chunks(
    chunk_store: SQLiteChunkStore, rating_store: SQLiteRatingStore
):
    c = _chunk("p1", cluster_id=None)
    chunk_store.save_many([c])
    sel = RatingSelector(chunk_store, rating_store)
    assert sel.next_chunk("p1") is None


def test_returns_none_when_all_rated(
    chunk_store: SQLiteChunkStore, rating_store: SQLiteRatingStore, session: Session
):
    c = _chunk("p1", cluster_id=0)
    chunk_store.save_many([c])
    rating_store.save(_rating("p1", c.id))
    sel = RatingSelector(chunk_store, rating_store)
    assert sel.next_chunk("p1") is None


def test_returns_unrated_chunk(
    chunk_store: SQLiteChunkStore, rating_store: SQLiteRatingStore
):
    c = _chunk("p1", cluster_id=0)
    chunk_store.save_many([c])
    sel = RatingSelector(chunk_store, rating_store)
    result = sel.next_chunk("p1")
    assert result is not None
    assert result.id == c.id


def test_prefers_underrepresented_cluster(
    chunk_store: SQLiteChunkStore, rating_store: SQLiteRatingStore, session: Session
):
    # cluster 0: 1 rated + 1 unrated; cluster 1: 0 rated + 1 unrated
    c0_rated = _chunk("p1", cluster_id=0, position=0)
    c0_unrated = _chunk("p1", cluster_id=0, position=1)
    c1_unrated = _chunk("p1", cluster_id=1, position=2)
    chunk_store.save_many([c0_rated, c0_unrated, c1_unrated])
    rating_store.save(_rating("p1", c0_rated.id))

    sel = RatingSelector(chunk_store, rating_store)
    # Should always pick from cluster 1 (0 ratings) not cluster 0 (1 rating)
    for _ in range(10):
        result = sel.next_chunk("p1")
        assert result.cluster_id == 1


def test_tiebreak_is_random(
    chunk_store: SQLiteChunkStore, rating_store: SQLiteRatingStore
):
    # Two clusters both with 0 ratings, one chunk each
    c0 = _chunk("p1", cluster_id=0, position=0)
    c1 = _chunk("p1", cluster_id=1, position=1)
    chunk_store.save_many([c0, c1])

    sel = RatingSelector(chunk_store, rating_store)
    seen_clusters: set[int] = set()
    for _ in range(20):
        result = sel.next_chunk("p1")
        if result:
            seen_clusters.add(result.cluster_id)
    assert 0 in seen_clusters
    assert 1 in seen_clusters
