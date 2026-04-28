"""Unit tests for ProfileCrystalliser — all LLM calls mocked with httpx."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from verdikt.core.models import Chunk, Domain, Project, Rating, RatingDimension
from verdikt.inference.crystalliser import ProfileCrystalliser, _truncate


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_project(dims: list[tuple[str, str]], threshold: int = 2) -> Project:
    return Project(
        name="Test",
        domain=Domain.TEXT,
        crystallisation_threshold=threshold,
        rating_dimensions=[
            RatingDimension(name=n, description=d, weight=1.0) for n, d in dims
        ],
    )


def _make_rating(
    project_id: str,
    chunk_id: str,
    material_item_id: str,
    scores: dict[str, float],
    skipped: bool = False,
) -> Rating:
    return Rating(
        project_id=project_id,
        chunk_id=chunk_id,
        material_item_id=material_item_id,
        dimension_scores=scores,
        skipped=skipped,
    )


def _make_chunk(chunk_id: str, content: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        project_id="proj",
        material_item_id="mat",
        content=content,
        position=0,
        size=len(content.split()),
    )


def _ollama_response(summary: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"response": json.dumps({"summary": summary})}
    return resp


def _make_crystalliser() -> ProfileCrystalliser:
    return ProfileCrystalliser(
        ollama_base_url="http://localhost:11434",
        model="llama3.1:8b",
    )


# ── _truncate ─────────────────────────────────────────────────────────────────

def test_truncate_short_text():
    assert _truncate("hello world", 10) == "hello world"


def test_truncate_long_text():
    words = ["word"] * 20
    result = _truncate(" ".join(words), 5)
    assert result == "word word word word word …"


def test_truncate_exact_limit():
    text = " ".join(["x"] * 10)
    assert _truncate(text, 10) == text


# ── crystallise ───────────────────────────────────────────────────────────────

def test_crystallise_returns_profile_with_correct_version():
    project = _make_project([("Prose", "Writing quality")])
    chunks = {"c1": _make_chunk("c1", "Great prose here " * 10)}
    ratings = [_make_rating(project.id, "c1", "m1", {"Prose": 4.0})]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("User likes clear prose.")
        profile, _, _ = c.crystallise(project, ratings, chunks, current_version=2)

    assert profile.version == 3


def test_crystallise_typical_score_is_mean_of_ratings():
    project = _make_project([("Style", "Writing style")])
    chunks = {
        "c1": _make_chunk("c1", "Alpha " * 20),
        "c2": _make_chunk("c2", "Beta " * 20),
        "c3": _make_chunk("c3", "Gamma " * 20),
    }
    ratings = [
        _make_rating(project.id, "c1", "m1", {"Style": 2.0}),
        _make_rating(project.id, "c2", "m1", {"Style": 4.0}),
        _make_rating(project.id, "c3", "m1", {"Style": 3.0}),
    ]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Mixed style preferences.")
        profile, _, _ = c.crystallise(project, ratings, chunks)

    dim = profile.dimensions[0]
    assert dim.name == "Style"
    assert dim.typical_score == pytest.approx(3.0)


def test_crystallise_skipped_ratings_excluded():
    project = _make_project([("Pacing", "Story pacing")])
    chunks = {"c1": _make_chunk("c1", "Fast pacing " * 15)}
    ratings = [
        _make_rating(project.id, "c1", "m1", {"Pacing": 5.0}),
        _make_rating(project.id, "c2", "m1", {}, skipped=True),
        _make_rating(project.id, "c3", "m1", {}, skipped=True),
    ]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Loves fast pacing.")
        profile, _, _ = c.crystallise(project, ratings, chunks)

    assert profile.rating_count == 1
    assert profile.dimensions[0].typical_score == pytest.approx(5.0)


def test_crystallise_no_ratings_for_dimension():
    project = _make_project([("Mood", "Emotional tone")])
    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Overall summary.")
        profile, _, _ = c.crystallise(project, [], {}, current_version=0)

    mock_post.assert_called_once()  # only the overall summary call
    dim = profile.dimensions[0]
    assert "No ratings" in dim.summary
    assert dim.typical_score == 0.0


def test_crystallise_multiple_dimensions_each_gets_llm_call():
    project = _make_project([("Prose", "Prose quality"), ("Plot", "Plot strength")])
    chunks = {
        "c1": _make_chunk("c1", "Great text " * 20),
        "c2": _make_chunk("c2", "Strong plot " * 20),
    }
    ratings = [
        _make_rating(project.id, "c1", "m1", {"Prose": 4.0, "Plot": 3.0}),
        _make_rating(project.id, "c2", "m1", {"Prose": 3.0, "Plot": 5.0}),
    ]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Some summary.")
        profile, _, _ = c.crystallise(project, ratings, chunks)

    # 2 dimension calls + 1 overall = 3 total
    assert mock_post.call_count == 3
    assert len(profile.dimensions) == 2


def test_crystallise_prompt_includes_dimension_name():
    project = _make_project([("Atmosphere", "Setting and mood")])
    chunks = {"c1": _make_chunk("c1", "Dark forest scene " * 15)}
    ratings = [_make_rating(project.id, "c1", "m1", {"Atmosphere": 5.0})]

    c = _make_crystalliser()
    captured_prompts = []
    def capture(url, **kwargs):
        captured_prompts.append(kwargs["json"]["prompt"])
        return _ollama_response("User loves dark atmosphere.")

    with patch("verdikt.inference.crystalliser.httpx.post", side_effect=capture):
        c.crystallise(project, ratings, chunks)

    dim_prompt = captured_prompts[0]
    assert "Atmosphere" in dim_prompt
    assert "Setting and mood" in dim_prompt


def test_crystallise_prompt_includes_high_and_low_examples():
    project = _make_project([("Quality", "Overall quality")])
    chunks = {f"c{i}": _make_chunk(f"c{i}", f"Content {i} " * 15) for i in range(6)}
    ratings = [
        _make_rating(project.id, f"c{i}", "m1", {"Quality": float(i + 1)})
        for i in range(6)
    ]

    c = _make_crystalliser()
    captured = []
    def capture(url, **kwargs):
        captured.append(kwargs["json"]["prompt"])
        return _ollama_response("Summary.")

    with patch("verdikt.inference.crystalliser.httpx.post", side_effect=capture):
        c.crystallise(project, ratings, chunks)

    dim_prompt = captured[0]
    assert "High-scoring" in dim_prompt
    assert "Low-scoring" in dim_prompt


def test_crystallise_long_content_truncated_in_prompt():
    project = _make_project([("Quality", "Quality")])
    long_content = "word " * 1000
    chunks = {"c1": _make_chunk("c1", long_content)}
    ratings = [_make_rating(project.id, "c1", "m1", {"Quality": 3.0})]

    c = _make_crystalliser()
    captured = []
    def capture(url, **kwargs):
        captured.append(kwargs["json"]["prompt"])
        return _ollama_response("Summary.")

    with patch("verdikt.inference.crystalliser.httpx.post", side_effect=capture):
        c.crystallise(project, ratings, chunks)

    assert "…" in captured[0]
    # Full 1000-word content should not appear verbatim
    assert "word " * 401 not in captured[0]


def test_crystallise_profile_metadata():
    project = _make_project([("Style", "Style")])
    chunks = {"c1": _make_chunk("c1", "Text " * 20)}
    ratings = [_make_rating(project.id, "c1", "m1", {"Style": 4.0})]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Prefers elegant style.")
        profile, _, _ = c.crystallise(project, ratings, chunks)

    assert profile.project_id == project.id
    assert profile.rating_count == 1
    assert profile.overall_summary == "Prefers elegant style."
    assert isinstance(profile.created_at, datetime)


def test_crystallise_overall_summary_references_dimensions():
    project = _make_project([("Prose", "Writing quality"), ("Plot", "Plot strength")])
    chunks = {
        "c1": _make_chunk("c1", "Fine text " * 20),
        "c2": _make_chunk("c2", "Great plot " * 20),
    }
    ratings = [
        _make_rating(project.id, "c1", "m1", {"Prose": 4.0, "Plot": 3.0}),
    ]

    c = _make_crystalliser()
    call_count = 0
    def side_effect(url, **kwargs):
        nonlocal call_count
        call_count += 1
        return _ollama_response(f"Summary {call_count}.")

    with patch("verdikt.inference.crystalliser.httpx.post", side_effect=side_effect):
        profile, _, _ = c.crystallise(project, ratings, chunks)

    # The last call is the overall summary; the prompt should include both dim summaries
    assert profile.overall_summary == "Summary 3."


def test_crystallise_missing_chunk_skipped_gracefully():
    project = _make_project([("Prose", "Quality")])
    # Rating references a chunk_id that is not in chunks_by_id
    ratings = [_make_rating(project.id, "missing_chunk", "m1", {"Prose": 5.0})]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Overall summary.")
        profile, _, _ = c.crystallise(project, ratings, {})

    # No crash; dimension falls back to "No ratings" (chunk content unavailable)
    assert "No ratings" in profile.dimensions[0].summary


# ── image domain ──────────────────────────────────────────────────────────────

def _make_image_chunk(chunk_id: str, position: int = 0) -> Chunk:
    return Chunk(
        id=chunk_id,
        project_id="proj",
        material_item_id="mat",
        content=b"\xff\xd8\xff",  # minimal JPEG header bytes
        position=position,
        size=1,
    )


def test_crystallise_image_chunks_included():
    """Image chunks (bytes content) must contribute to scored ratings."""
    project = Project(
        name="Images",
        domain=Domain.IMAGE,
        crystallisation_threshold=1,
        rating_dimensions=[RatingDimension(name="Composition", description="Balance", weight=1.0)],
    )
    chunks = {
        "img1": _make_image_chunk("img1", position=0),
        "img2": _make_image_chunk("img2", position=1),
    }
    ratings = [
        _make_rating(project.id, "img1", "m1", {"Composition": 5.0}),
        _make_rating(project.id, "img2", "m1", {"Composition": 2.0}),
    ]

    c = _make_crystalliser()
    with patch("verdikt.inference.crystalliser.httpx.post") as mock_post:
        mock_post.return_value = _ollama_response("Prefers balanced compositions.")
        profile, _, _ = c.crystallise(project, ratings, chunks)

    dim = profile.dimensions[0]
    assert dim.name == "Composition"
    assert dim.typical_score == pytest.approx(3.5)
    assert dim.summary == "Prefers balanced compositions."


def test_crystallise_image_chunk_label_uses_position():
    """The LLM prompt for image chunks must contain a positional label, not raw bytes."""
    project = Project(
        name="Images",
        domain=Domain.IMAGE,
        crystallisation_threshold=1,
        rating_dimensions=[RatingDimension(name="Lighting", description="Light quality", weight=1.0)],
    )
    chunks = {"img0": _make_image_chunk("img0", position=2)}
    ratings = [_make_rating(project.id, "img0", "m1", {"Lighting": 4.0})]

    c = _make_crystalliser()
    captured_prompts: list[str] = []
    def _capture(url, json, **kwargs):
        captured_prompts.append(json.get("prompt", ""))
        return _ollama_response("Good lighting.")

    with patch("verdikt.inference.crystalliser.httpx.post", side_effect=_capture):
        c.crystallise(project, ratings, chunks)

    assert any("[image #3]" in p for p in captured_prompts), "Expected positional label in prompt"
    assert not any(b"\xff\xd8" in p.encode("utf-8", errors="replace") for p in captured_prompts), \
        "Raw bytes must not appear in prompt"
