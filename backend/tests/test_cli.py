"""Tests for verdikt.cli — all commands, no heavy dependencies required."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from click.testing import CliRunner

from verdikt.cli import app
from verdikt.core.models import Domain, Project
from verdikt.inference.base import EmbedderBase
from verdikt.pipeline.runner import PhaseResult, PipelineResult
from verdikt.storage.base import VectorStore


# ── Test doubles ─────────────────────────────────────────────────────────────

class _MockEmbedder(EmbedderBase):
    _DIM = 8

    def embed(self, inputs):
        rng = np.random.default_rng(42)
        return rng.random((len(inputs), self._DIM)).astype(np.float32)

    @property
    def dimension(self):
        return self._DIM


class _MockVectorStore(VectorStore):
    def __init__(self):
        self._data = {}

    def upsert(self, item_id, embedding, metadata):
        self._data[item_id] = embedding

    def query(self, embedding, n_results, where=None):
        return []

    def delete_collection(self):
        self._data.clear()

    def delete_items(self, ids):
        for i in ids:
            self._data.pop(i, None)

    def get_all_embeddings(self):
        ids = list(self._data.keys())
        embs = np.array([self._data[i] for i in ids], dtype=np.float32) if ids else np.empty((0,), dtype=np.float32)
        return ids, embs


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def env(tmp_path):
    return {"VERDIKT_DATA_DIR": str(tmp_path)}


@pytest.fixture
def project_env(runner, env):
    """Create a project and return (runner, env, project_id)."""
    result = runner.invoke(app, ["project", "create", "TestProject"], env=env)
    assert result.exit_code == 0
    project_id = result.output.strip().split()[2]
    return runner, env, project_id


# ── project create ────────────────────────────────────────────────────────────

def test_project_create(runner, env):
    result = runner.invoke(app, ["project", "create", "My Novel"], env=env)
    assert result.exit_code == 0
    assert "My Novel" in result.output


def test_project_create_with_description(runner, env):
    result = runner.invoke(
        app, ["project", "create", "Fantasy", "--description", "Dark fantasy fiction"], env=env
    )
    assert result.exit_code == 0
    assert "Fantasy" in result.output


def test_project_create_invalid_domain(runner, env):
    result = runner.invoke(app, ["project", "create", "X", "--domain", "video"], env=env)
    assert result.exit_code != 0


# ── project list ──────────────────────────────────────────────────────────────

def test_project_list_empty(runner, env):
    result = runner.invoke(app, ["project", "list"], env=env)
    assert result.exit_code == 0
    assert "No projects" in result.output


def test_project_list_shows_projects(runner, env):
    runner.invoke(app, ["project", "create", "Alpha"], env=env)
    runner.invoke(app, ["project", "create", "Beta"], env=env)
    result = runner.invoke(app, ["project", "list"], env=env)
    assert result.exit_code == 0
    assert "Alpha" in result.output
    assert "Beta" in result.output


# ── project show ──────────────────────────────────────────────────────────────

def test_project_show_by_name(runner, env):
    runner.invoke(app, ["project", "create", "ShowMe", "--description", "desc"], env=env)
    result = runner.invoke(app, ["project", "show", "ShowMe"], env=env)
    assert result.exit_code == 0
    assert "ShowMe" in result.output
    assert "desc" in result.output


def test_project_show_unknown(runner, env):
    result = runner.invoke(app, ["project", "show", "ghost"], env=env)
    assert result.exit_code != 0


# ── project works ─────────────────────────────────────────────────────────────

def test_project_works_empty(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["project", "works", pid], env=env)
    assert result.exit_code == 0
    assert "No works" in result.output


def test_project_works_after_ingest(tmp_path, project_env):
    runner, env, pid = project_env
    (tmp_path / "book.txt").write_text("Hello world " * 50)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    result = runner.invoke(app, ["project", "works", pid], env=env)
    assert result.exit_code == 0
    assert "book.txt" in result.output


# ── project delete ────────────────────────────────────────────────────────────

def test_project_delete_yes_flag(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["project", "delete", pid, "--yes"], env=env)
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_project_delete_confirms_prompt(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["project", "delete", pid], input="y\n", env=env)
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_project_delete_abort(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["project", "delete", pid], input="n\n", env=env)
    assert result.exit_code != 0
    # Project should still exist
    check = runner.invoke(app, ["project", "show", pid], env=env)
    assert check.exit_code == 0


# ── ingest ────────────────────────────────────────────────────────────────────

def test_ingest_adds_files(tmp_path, project_env):
    runner, env, pid = project_env
    content_dir = tmp_path / "books"
    content_dir.mkdir()
    (content_dir / "story.txt").write_text("Once upon a time " * 30)
    (content_dir / "notes.md").write_text("# Notes\n\nSome content here " * 20)
    result = runner.invoke(app, ["ingest", pid, str(content_dir)], env=env)
    assert result.exit_code == 0
    assert "added: 2" in result.output


def test_ingest_idempotent(tmp_path, project_env):
    runner, env, pid = project_env
    f = tmp_path / "file.txt"
    f.write_text("Same content " * 40)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    result = runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    assert result.exit_code == 0
    assert "unchanged: 1" in result.output


def test_ingest_updates_changed_file(tmp_path, project_env):
    runner, env, pid = project_env
    f = tmp_path / "file.txt"
    f.write_text("Original content " * 40)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    f.write_text("Updated content " * 40)
    result = runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    assert result.exit_code == 0
    assert "updated: 1" in result.output


def test_ingest_nonexistent_dir(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["ingest", pid, "/nonexistent/path/xyz"], env=env)
    assert result.exit_code != 0


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_single_file(tmp_path, project_env):
    runner, env, pid = project_env
    f = tmp_path / "story.txt"
    f.write_text("A great story " * 40)
    result = runner.invoke(app, ["add", pid, str(f)], env=env)
    assert result.exit_code == 0
    assert "Added" in result.output


def test_add_updates_changed_file(tmp_path, project_env):
    runner, env, pid = project_env
    f = tmp_path / "story.txt"
    f.write_text("Version one " * 40)
    runner.invoke(app, ["add", pid, str(f)], env=env)
    f.write_text("Version two " * 40)
    result = runner.invoke(app, ["add", pid, str(f)], env=env)
    assert result.exit_code == 0
    assert "Updated" in result.output


def test_add_unchanged_file(tmp_path, project_env):
    runner, env, pid = project_env
    f = tmp_path / "story.txt"
    f.write_text("Same story " * 40)
    runner.invoke(app, ["add", pid, str(f)], env=env)
    result = runner.invoke(app, ["add", pid, str(f)], env=env)
    assert result.exit_code == 0
    assert "unchanged" in result.output


def test_add_unsupported_extension(tmp_path, project_env):
    runner, env, pid = project_env
    f = tmp_path / "video.mp4"
    f.write_bytes(b"\x00" * 16)
    result = runner.invoke(app, ["add", pid, str(f)], env=env)
    assert result.exit_code != 0
    assert "Unsupported" in result.output


def test_add_nonexistent_file(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["add", pid, "/no/such/file.txt"], env=env)
    assert result.exit_code != 0


# ── remove ────────────────────────────────────────────────────────────────────

def test_remove_by_seq(tmp_path, project_env):
    runner, env, pid = project_env
    (tmp_path / "book.txt").write_text("Content " * 50)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    result = runner.invoke(app, ["remove", pid, "1"], env=env)
    assert result.exit_code == 0
    assert "Removed" in result.output


def test_remove_nonexistent_ref(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["remove", pid, "999"], env=env)
    assert result.exit_code != 0


# ── work show ─────────────────────────────────────────────────────────────────

def test_work_show(tmp_path, project_env):
    runner, env, pid = project_env
    (tmp_path / "novel.txt").write_text("Chapter one " * 50)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)
    result = runner.invoke(app, ["work", "show", pid, "1"], env=env)
    assert result.exit_code == 0
    assert "novel" in result.output.lower()


def test_work_show_unknown(project_env):
    runner, env, pid = project_env
    result = runner.invoke(app, ["work", "show", pid, "99"], env=env)
    assert result.exit_code != 0


# ── pipeline run ──────────────────────────────────────────────────────────────

def _mock_pipeline_result(project_id: str) -> PipelineResult:
    return PipelineResult(
        project_id=project_id,
        phases=[PhaseResult("chunk", 3), PhaseResult("embed", 3), PhaseResult("cluster", 3)],
    )


def test_pipeline_run(tmp_path, project_env):
    runner, env, pid = project_env
    (tmp_path / "text.txt").write_text("Sample content " * 60)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)

    mock_vector_store = _MockVectorStore()
    with (
        patch("verdikt.cli.SentenceTransformerEmbedder", return_value=_MockEmbedder()),
        patch("verdikt.cli._make_vector_store", return_value=mock_vector_store),
    ):
        result = runner.invoke(app, ["pipeline", "run", pid], env=env)

    assert result.exit_code == 0
    assert "Done" in result.output


def test_pipeline_run_nothing_to_do(project_env):
    runner, env, pid = project_env
    mock_result = PipelineResult(project_id=pid, phases=[])
    with (
        patch("verdikt.cli.SentenceTransformerEmbedder", return_value=_MockEmbedder()),
        patch("verdikt.cli.run_pipeline_flow", return_value=mock_result),
    ):
        result = runner.invoke(app, ["pipeline", "run", pid], env=env)
    assert result.exit_code == 0
    assert "Nothing to do" in result.output


def test_pipeline_run_work(tmp_path, project_env):
    runner, env, pid = project_env
    (tmp_path / "text.txt").write_text("Sample content " * 60)
    runner.invoke(app, ["ingest", pid, str(tmp_path)], env=env)

    mock_vector_store = _MockVectorStore()
    with (
        patch("verdikt.cli.SentenceTransformerEmbedder", return_value=_MockEmbedder()),
        patch("verdikt.cli._make_vector_store", return_value=mock_vector_store),
    ):
        result = runner.invoke(app, ["pipeline", "run-work", pid, "1"], env=env)

    assert result.exit_code == 0
    assert "Done" in result.output


def test_pipeline_run_work_unknown_ref(project_env):
    runner, env, pid = project_env
    with patch("verdikt.cli.SentenceTransformerEmbedder", return_value=_MockEmbedder()):
        result = runner.invoke(app, ["pipeline", "run-work", pid, "99"], env=env)
    assert result.exit_code != 0


# ── serve ─────────────────────────────────────────────────────────────────────

def test_serve_calls_uvicorn(runner, env):
    with patch("uvicorn.run") as mock_run:
        runner.invoke(app, ["serve", "--port", "9999"], env=env)
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs.get("port") == 9999


def test_serve_reload_flag(runner, env):
    with patch("uvicorn.run") as mock_run:
        runner.invoke(app, ["serve", "--reload"], env=env)
    _, kwargs = mock_run.call_args
    assert kwargs.get("reload") is True
