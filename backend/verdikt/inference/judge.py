from __future__ import annotations

import base64
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
        chunk_content: str | bytes,
        profile: PreferenceProfile,
        project: Project,
    ) -> tuple[dict[str, float], float, dict[str, str]]:
        """Score a chunk against a preference profile.

        chunk_content may be a text string or raw image bytes.
        Returns (dimension_scores, weighted_overall_score, explanations).
        """
        weights = {d.name: d.weight for d in project.rating_dimensions}
        typical = {d.name: d.typical_score for d in profile.dimensions}

        dim_lines = "\n".join(
            f"- {d.name}: {d.summary} (typical score: {d.typical_score:.1f}/5)"
            for d in profile.dimensions
        )
        dim_keys = ", ".join(f'"{d.name}"' for d in profile.dimensions)

        is_image = isinstance(chunk_content, bytes)
        content_label = "image" if is_image else "passage"

        prompt = (
            f"You are evaluating an {content_label} for a person with specific preferences.\n\n"
            f"Preferences:\n{profile.overall_summary}\n\n"
            f"Dimension preferences:\n{dim_lines}\n\n"
            f"For each dimension, respond with a JSON object only (no prose, no markdown):\n"
            f"{{{dim_keys}: {{\"score\": <int 1-5>, \"explanation\": \"<one sentence>\"}}, ...}}"
        )
        if not is_image:
            prompt = (
                f"You are evaluating a {content_label} for a person with specific preferences.\n\n"
                f"Preferences:\n{profile.overall_summary}\n\n"
                f"Dimension preferences:\n{dim_lines}\n\n"
                f"{content_label.capitalize()} to evaluate:\n{_truncate(chunk_content)}\n\n"
                f"For each dimension, respond with a JSON object only (no prose, no markdown):\n"
                f"{{{dim_keys}: {{\"score\": <int 1-5>, \"explanation\": \"<one sentence>\"}}, ...}}"
            )

        image_b64 = base64.b64encode(chunk_content).decode() if is_image else None
        raw = self._call_ollama(prompt, image_b64)
        scores, explanations = self._parse_response(raw, typical)
        overall = self._weighted_average(scores, weights)
        return scores, overall, explanations

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        text = raw.strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        import re
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except (json.JSONDecodeError, ValueError):
                pass
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def _call_ollama(self, prompt: str, image_b64: str | None = None) -> str:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        if image_b64 is not None:
            payload["images"] = [image_b64]

        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self._base_url}. "
                "Check that Ollama is running and VERDIKT_INFERENCE__OLLAMA_BASE_URL is correct."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            if status == 404:
                raise RuntimeError(
                    f"Model '{self._model}' not found in Ollama. "
                    f"Run 'ollama pull {self._model}' or choose a different model in the project settings."
                ) from exc
            if image_b64 and ("vision" in body.lower() or "multimodal" in body.lower() or "image" in body.lower()):
                raise RuntimeError(
                    f"Model '{self._model}' does not support image input. "
                    "Use a vision-capable model such as llava or llama3.2-vision for image projects."
                ) from exc
            raise RuntimeError(f"Ollama returned {status}: {body}") from exc

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
