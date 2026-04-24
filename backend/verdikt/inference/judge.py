from __future__ import annotations

import json
import logging

import httpx

from verdikt.core.models import PreferenceProfile, Project

log = logging.getLogger(__name__)

_MAX_WORDS = 400


def _truncate(text: str, max_words: int = _MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


class LLMJudge:
    def __init__(self, ollama_base_url: str, model: str) -> None:
        self._base_url = ollama_base_url.rstrip("/")
        self._model = model

    def score_chunk(
        self,
        chunk_content: str,
        profile: PreferenceProfile,
        project: Project,
    ) -> tuple[dict[str, float], float, dict[str, str]]:
        """Score a chunk against a preference profile.

        Returns (dimension_scores, weighted_overall_score, explanations).
        On any parse failure, falls back to typical_score for that dimension.
        """
        weights = {d.name: d.weight for d in project.rating_dimensions}
        typical = {d.name: d.typical_score for d in profile.dimensions}

        dim_lines = "\n".join(
            f"- {d.name}: {d.summary} (typical score: {d.typical_score:.1f}/5)"
            for d in profile.dimensions
        )
        dim_keys = ", ".join(f'"{d.name}"' for d in profile.dimensions)

        prompt = (
            f"You are evaluating a passage for a reader with specific preferences.\n\n"
            f"Reader profile:\n{profile.overall_summary}\n\n"
            f"Dimension preferences:\n{dim_lines}\n\n"
            f"Passage to evaluate:\n{_truncate(chunk_content)}\n\n"
            f"For each dimension, respond with a JSON object only (no prose, no markdown):\n"
            f"{{{dim_keys}: {{\"score\": <int 1-5>, \"explanation\": \"<one sentence>\"}}, ...}}"
        )

        raw = self._call_ollama(prompt)
        scores, explanations = self._parse_response(raw, typical)
        overall = self._weighted_average(scores, weights)
        return scores, overall, explanations

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        """Try several strategies to extract a JSON object from LLM output."""
        text = raw.strip()

        # Direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Strip markdown fences: ```json ... ``` or ``` ... ```
        import re
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # Find the first { ... } block in the text
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    def _call_ollama(self, prompt: str) -> str:
        resp = httpx.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _parse_response(self, raw: str, typical: dict[str, float]) -> tuple[dict[str, float], dict[str, str]]:
        scores: dict[str, float] = {}
        explanations: dict[str, str] = {}
        data = self._extract_json(raw)
        if data is None:
            log.warning("LLMJudge: failed to parse JSON response, using typical scores")
            return dict(typical), {}

        for dim_name, fallback in typical.items():
            entry = data.get(dim_name)
            if not isinstance(entry, dict):
                log.warning("LLMJudge: missing dimension %r in response, using typical score", dim_name)
                scores[dim_name] = fallback
                continue
            raw_score = entry.get("score")
            try:
                score = float(raw_score)
                scores[dim_name] = max(1.0, min(5.0, score))
            except (TypeError, ValueError):
                log.warning("LLMJudge: invalid score for %r, using typical score", dim_name)
                scores[dim_name] = fallback
            expl = entry.get("explanation")
            if isinstance(expl, str) and expl.strip():
                explanations[dim_name] = expl.strip()

        return scores, explanations

    @staticmethod
    def _weighted_average(scores: dict[str, float], weights: dict[str, float]) -> float:
        total_weight = sum(weights.get(k, 1.0) for k in scores)
        if total_weight == 0:
            return sum(scores.values()) / len(scores) if scores else 0.0
        return sum(v * weights.get(k, 1.0) for k, v in scores.items()) / total_weight
