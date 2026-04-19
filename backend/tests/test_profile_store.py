import pytest
from sqlalchemy.orm import Session

from verdikt.core.models import DimensionProfile, PreferenceProfile
from verdikt.storage.sqlite import SQLiteProfileStore


@pytest.fixture
def store(session: Session) -> SQLiteProfileStore:
    return SQLiteProfileStore(session)


def _profile(project_id: str, version: int = 1, rating_count: int = 10) -> PreferenceProfile:
    return PreferenceProfile(
        project_id=project_id,
        version=version,
        dimensions=[
            DimensionProfile(name="Prose", description="style", summary="loves vivid prose", typical_score=4.2),
        ],
        overall_summary="Prefers literary fiction.",
        rating_count=rating_count,
    )


def test_save_and_get_latest(store: SQLiteProfileStore):
    p = _profile("proj1")
    store.save(p)
    latest = store.get_latest("proj1")
    assert latest is not None
    assert latest.id == p.id
    assert latest.overall_summary == "Prefers literary fiction."


def test_get_latest_returns_highest_version(store: SQLiteProfileStore):
    store.save(_profile("proj1", version=1))
    store.save(_profile("proj1", version=3))
    store.save(_profile("proj1", version=2))
    latest = store.get_latest("proj1")
    assert latest.version == 3


def test_get_latest_none_when_empty(store: SQLiteProfileStore):
    assert store.get_latest("no-such-project") is None


def test_list_versions(store: SQLiteProfileStore):
    store.save(_profile("proj1", version=1))
    store.save(_profile("proj1", version=2))
    versions = store.list_versions("proj1")
    assert len(versions) == 2
    assert versions[0].version == 2  # descending order


def test_update(store: SQLiteProfileStore):
    p = _profile("proj1")
    store.save(p)
    p.overall_summary = "Updated summary."
    p.dimensions[0].summary = "Updated dimension summary."
    store.update(p)
    fetched = store.get_latest("proj1")
    assert fetched.overall_summary == "Updated summary."
    assert fetched.dimensions[0].summary == "Updated dimension summary."
