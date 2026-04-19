import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.models import Domain, Project, RatingDimension
from verdikt.storage.orm import Base


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "infra: requires running Ollama and ChromaDB (skip with -m 'not infra')",
    )


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def sample_project() -> Project:
    return Project(name="Test Project", domain=Domain.TEXT)


@pytest.fixture
def sample_project_with_dims() -> Project:
    return Project(
        name="Test Project With Dims",
        domain=Domain.TEXT,
        rating_dimensions=[
            RatingDimension(name="Prose Quality", description="Clarity and style", weight=1.0),
            RatingDimension(name="Pacing", description="Narrative flow", weight=1.0),
        ],
        crystallisation_threshold=2,
    )


@pytest.fixture
def tmp_file_dir(tmp_path):
    return tmp_path
