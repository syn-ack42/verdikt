import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "infra: requires running Ollama and ChromaDB (skip with -m 'not infra')",
    )
