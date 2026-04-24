from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from verdikt.core.models import DimensionProfile, PreferenceProfile, Project, RatingDimension
from verdikt.inference.judge import LLMJudge


@pytest.fixture
def project() -> Project:
    return Project(
        name="Test",
        rating_dimensions=[
            RatingDimension(name="Prose", description="Writing quality", weight=2.0),
            RatingDimension(name="Pacing", description="Story speed", weight=1.0),
        ],
    )


@pytest.fixture
def profile(project: Project) -> PreferenceProfile:
    return PreferenceProfile(
        project_id=project.id,
        overall_summary="Prefers rich, literary prose with measured pacing.",
        dimensions=[
            DimensionProfile(name="Prose", description="Writing quality", summary="Loves vivid imagery.", typical_score=4.2),
            DimensionProfile(name="Pacing", description="Story speed", summary="Prefers measured pace.", typical_score=3.5),
        ],
        rating_count=20,
    )


@pytest.fixture
def judge() -> LLMJudge:
    return LLMJudge("http://localhost:11434", "llama3.1:8b")


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"response": json.dumps(data)}
    resp.raise_for_status = MagicMock()
    return resp


def test_weighted_score_calculation(judge, project, profile):
    payload = {
        "Prose": {"score": 5, "explanation": "Excellent writing."},
        "Pacing": {"score": 3, "explanation": "Steady pace."},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        scores, overall, _ = judge.score_chunk("Some text.", profile, project)

    assert scores == {"Prose": 5.0, "Pacing": 3.0}
    # Weighted: (5 * 2 + 3 * 1) / 3 = 13/3 ≈ 4.333
    assert abs(overall - 13 / 3) < 0.01


def test_prompt_contains_profile_summary(judge, project, profile):
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(
        {"Prose": {"score": 4, "explanation": "ok"}, "Pacing": {"score": 4, "explanation": "ok"}}
    )) as mock_post:
        judge.score_chunk("Text", profile, project)

    call_kwargs = mock_post.call_args
    prompt = call_kwargs[1]["json"]["prompt"]
    assert "rich, literary prose" in prompt
    assert "Loves vivid imagery" in prompt
    assert "Prefers measured pace" in prompt


def test_truncation_applied(judge, project, profile):
    long_text = " ".join(["word"] * 600)
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(
        {"Prose": {"score": 3, "explanation": "ok"}, "Pacing": {"score": 3, "explanation": "ok"}}
    )) as mock_post:
        judge.score_chunk(long_text, profile, project)

    prompt = mock_post.call_args[1]["json"]["prompt"]
    assert "…" in prompt


def test_json_parse_error_falls_back_to_typical(judge, project, profile):
    resp = MagicMock()
    resp.json.return_value = {"response": "not json at all"}
    resp.raise_for_status = MagicMock()
    with patch("verdikt.inference.judge.httpx.post", return_value=resp):
        scores, overall, _ = judge.score_chunk("Text", profile, project)

    assert scores["Prose"] == pytest.approx(4.2)
    assert scores["Pacing"] == pytest.approx(3.5)


def test_missing_dimension_key_falls_back_to_typical(judge, project, profile):
    payload = {"Prose": {"score": 5, "explanation": "great"}}  # Pacing missing
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        scores, overall, _ = judge.score_chunk("Text", profile, project)

    assert scores["Prose"] == 5.0
    assert scores["Pacing"] == pytest.approx(3.5)


def test_score_clamped_to_1_5(judge, project, profile):
    payload = {
        "Prose": {"score": 99, "explanation": "extreme"},
        "Pacing": {"score": -1, "explanation": "negative"},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        scores, _overall, _ = judge.score_chunk("Text", profile, project)

    assert scores["Prose"] == 5.0
    assert scores["Pacing"] == 1.0


def test_explanations_extracted(judge, project, profile):
    payload = {
        "Prose": {"score": 5, "explanation": "Vivid and precise."},
        "Pacing": {"score": 3, "explanation": "Unhurried but steady."},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        _, _, explanations = judge.score_chunk("Some text.", profile, project)

    assert explanations["Prose"] == "Vivid and precise."
    assert explanations["Pacing"] == "Unhurried but steady."


def test_explanations_empty_on_parse_error(judge, project, profile):
    resp = MagicMock()
    resp.json.return_value = {"response": "not json"}
    resp.raise_for_status = MagicMock()
    with patch("verdikt.inference.judge.httpx.post", return_value=resp):
        _, _, explanations = judge.score_chunk("Text", profile, project)

    assert explanations == {}


def test_explanations_partial_when_dimension_missing(judge, project, profile):
    payload = {"Prose": {"score": 4, "explanation": "Good prose."}}  # Pacing missing
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        _, _, explanations = judge.score_chunk("Text", profile, project)

    assert explanations["Prose"] == "Good prose."
    assert "Pacing" not in explanations
