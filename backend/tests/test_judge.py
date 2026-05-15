from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from verdikt.core.models import DimensionProfile, PreferenceProfile, Project, RatingDimension
from verdikt.inference.judge import LLMJudge
from verdikt.inference.resolver import LLMTarget


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
    target = LLMTarget(provider="ollama", base_url="http://localhost:11434", model="llama3.1:8b")
    return LLMJudge(target)


def _mock_response(data: dict) -> MagicMock:
    """Ollama-format mock response."""
    resp = MagicMock()
    resp.json.return_value = {"response": json.dumps(data)}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_venice_response(data: dict, prompt_tokens: int = 10, completion_tokens: int = 5) -> MagicMock:
    """OpenAI-compat mock response (Venice format)."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(data)}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    return resp


@pytest.fixture
def venice_judge() -> LLMJudge:
    target = LLMTarget(provider="venice", base_url="https://api.venice.ai/api/v1", model="llama-3.3-70b", api_key="sk-test")
    return LLMJudge(target)


def test_weighted_score_calculation(judge, project, profile):
    payload = {
        "Prose": {"score": 5, "explanation": "Excellent writing."},
        "Pacing": {"score": 3, "explanation": "Steady pace."},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        scores, overall, _, _desc = judge.score_chunk("Some text.", profile, project)

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
        scores, overall, _, _desc = judge.score_chunk("Text", profile, project)

    assert scores["Prose"] == pytest.approx(4.2)
    assert scores["Pacing"] == pytest.approx(3.5)


def test_missing_dimension_key_falls_back_to_typical(judge, project, profile):
    payload = {"Prose": {"score": 5, "explanation": "great"}}  # Pacing missing
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        scores, overall, _, _desc = judge.score_chunk("Text", profile, project)

    assert scores["Prose"] == 5.0
    assert scores["Pacing"] == pytest.approx(3.5)


def test_score_clamped_to_1_5(judge, project, profile):
    payload = {
        "Prose": {"score": 99, "explanation": "extreme"},
        "Pacing": {"score": -1, "explanation": "negative"},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        scores, _overall, _, _desc = judge.score_chunk("Text", profile, project)

    assert scores["Prose"] == 5.0
    assert scores["Pacing"] == 1.0


def test_explanations_extracted(judge, project, profile):
    payload = {
        "Prose": {"score": 5, "explanation": "Vivid and precise."},
        "Pacing": {"score": 3, "explanation": "Unhurried but steady."},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        _, _, explanations, _desc = judge.score_chunk("Some text.", profile, project)

    assert explanations["Prose"] == "Vivid and precise."
    assert explanations["Pacing"] == "Unhurried but steady."


def test_explanations_empty_on_parse_error(judge, project, profile):
    resp = MagicMock()
    resp.json.return_value = {"response": "not json"}
    resp.raise_for_status = MagicMock()
    with patch("verdikt.inference.judge.httpx.post", return_value=resp):
        _, _, explanations, _desc = judge.score_chunk("Text", profile, project)

    assert explanations == {}


def test_explanations_partial_when_dimension_missing(judge, project, profile):
    payload = {"Prose": {"score": 4, "explanation": "Good prose."}}  # Pacing missing
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_response(payload)):
        _, _, explanations, _desc = judge.score_chunk("Text", profile, project)

    assert explanations["Prose"] == "Good prose."
    assert "Pacing" not in explanations


# ── Venice path ───────────────────────────────────────────────────────────────

def test_venice_scores_extracted(venice_judge, project, profile):
    payload = {
        "Prose": {"score": 4, "explanation": "Vivid prose."},
        "Pacing": {"score": 3, "explanation": "Measured."},
    }
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_venice_response(payload)):
        scores, overall, explanations, _desc = venice_judge.score_chunk("Some text.", profile, project)

    assert scores == {"Prose": 4.0, "Pacing": 3.0}
    assert explanations["Prose"] == "Vivid prose."


def test_venice_uses_chat_completions_endpoint(venice_judge, project, profile):
    payload = {"Prose": {"score": 3, "explanation": "ok"}, "Pacing": {"score": 3, "explanation": "ok"}}
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_venice_response(payload)) as mock_post:
        venice_judge.score_chunk("Text", profile, project)

    url = mock_post.call_args[0][0]
    assert "chat/completions" in url
    headers = mock_post.call_args[1]["json"] if "json" in mock_post.call_args[1] else mock_post.call_args.kwargs.get("json", {})
    # Authorization header must include the api key
    assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer sk-test"


def test_venice_token_usage_returned(venice_judge, project, profile):
    payload = {"Prose": {"score": 3, "explanation": "ok"}, "Pacing": {"score": 3, "explanation": "ok"}}
    with patch("verdikt.inference.judge.httpx.post", return_value=_mock_venice_response(payload, prompt_tokens=20, completion_tokens=8)):
        venice_judge.score_chunk("Text", profile, project)

    assert venice_judge.usage == [(20, 8)]


def test_venice_401_raises_readable_error(venice_judge, project, profile):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    exc = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
    with patch("verdikt.inference.judge.httpx.post", side_effect=exc):
        with pytest.raises(RuntimeError, match="Venice API key is invalid"):
            venice_judge.score_chunk("Text", profile, project)


def test_venice_404_raises_model_not_found(venice_judge, project, profile):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not found"
    exc = httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)
    with patch("verdikt.inference.judge.httpx.post", side_effect=exc):
        with pytest.raises(RuntimeError, match="not found on Venice"):
            venice_judge.score_chunk("Text", profile, project)
