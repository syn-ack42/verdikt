import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.models import Domain, Project
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
def tmp_file_dir(tmp_path):
    return tmp_path
