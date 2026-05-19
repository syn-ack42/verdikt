from __future__ import annotations

import base64
import json
import logging

import httpx

from verdikt.core.models import PreferenceProfile, Project
from verdikt.inference.prompts import PROMPT_KEYS, load_prompts, render
from verdikt.inference.resolver import LLMTarget

log = logging.getLogger(__name__)

_MAX_WORDS = 400


def _truncate(text: str, max_words: int = _MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


class LLMJudge:
    def __init__(
        self,
        target: LLMTarget,
        timeout: float = 300.0,
        temperature: float | None = None,
        prompts: dict[str, str] | None = None,
    ) -> None:
        self._target = target
        self._timeout = timeout
        self._temperature = temperature
        self._prompts = prompts or dict(PROMPT_KEYS)
        # Accumulates (prompt_tokens, completion_tokens) per call; flush after each run.
        self.usage: list[tuple[int, int]] = []

    def score_chunk(
        self,
        chunk_content: str | bytes,
        profile: PreferenceProfile,
        project: Project,
    ) -> tuple[dict[str, float], float, dict[str, str], str | None]:
        """Score a chunk against a preference profile.

        chunk_content may be a text string or raw image bytes.
        Returns (dimension_scores, weighted_overall_score, explanations, description).
        """
        weights = {d.name: d.weight for d in project.rating_dimensions}
        typical = {d.name: d.typical_score for d in profile.dimensions}

        dim_lines = "\n".join(
            f"- {d.name}: {d.summary} (typical score: {d.typical_score:.1f}/5)"
            for d in profile.dimensions
        )
        is_image = isinstance(chunk_content, bytes)
        content_label = "image" if is_image else "passage"
        description_hint = (
            "1-2 sentence neutral factual description of what the image shows (subject, setting, mood, composition) — no evaluative language"
            if is_image else
            "1-2 sentence neutral factual description of what the passage is about (topic, scene, content type, narrative voice) — no evaluative language"
        )

        score_rubric = self._prompts.get("prompt.judge.score_rubric", PROMPT_KEYS["prompt.judge.score_rubric"])

        # Build an explicit per-dimension schema so the model knows exactly what keys to emit
        dim_schema = ",\n".join(
            f'  "{d.name}": {{"score": <int 1-5>, "explanation": "<one sentence why>"}}'
            for d in profile.dimensions
        )
        response_schema = f'{{\n{dim_schema},\n  "description": "<{description_hint}>"\n}}'

        template_key = "prompt.judge.image" if is_image else "prompt.judge.text"
        template = self._prompts.get(template_key, PROMPT_KEYS[template_key])
        prompt = render(
            template,
            SCORE_RUBRIC=score_rubric,
            OVERALL_SUMMARY=profile.overall_summary,
            DIM_LINES=dim_lines,
            CONTENT="" if is_image else _truncate(chunk_content),  # type: ignore[arg-type]
            RESPONSE_SCHEMA=response_schema,
        )

        image_b64 = base64.b64encode(chunk_content).decode() if is_image else None
        raw, prompt_tokens, completion_tokens = self._call_llm(prompt, image_b64)
        self.usage.append((prompt_tokens, completion_tokens))
        scores, explanations, description = self._parse_response(raw, typical)
        overall = self._weighted_average(scores, weights)
        return scores, overall, explanations, description

    def _call_llm(self, prompt: str, image_b64: str | None = None) -> tuple[str, int, int]:
        if self._target.provider in ("venice", "openrouter"):
            return self._call_openai_compat(prompt, image_b64)
        return self._call_ollama(prompt, image_b64)

    def _call_openai_compat(self, prompt: str, image_b64: str | None = None) -> tuple[str, int, int]:
        if image_b64 is not None:
            content: object = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]
        else:
            content = prompt

        try:
            resp = httpx.post(
                f"{self._target.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._target.api_key}"},
                json={
                    "model": self._target.model,
                    "messages": [{"role": "user", "content": content}],
                    "response_format": {"type": "json_object"},
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(f"Cannot reach {self._target.provider} API at {self._target.base_url}.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            provider = self._target.provider.capitalize()
            if status == 401:
                raise RuntimeError(f"{provider} API key is invalid or expired.") from exc
            if status == 404:
                raise RuntimeError(
                    f"Model '{self._target.model}' not found on {provider}. "
                    "Sync models and check the project's model setting."
                ) from exc
            raise RuntimeError(f"{provider} API returned {status}: {body}") from exc

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)

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

    def _call_ollama(self, prompt: str, image_b64: str | None = None) -> tuple[str, int, int]:
        payload: dict = {
            "model": self._target.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        if self._temperature is not None:
            payload["options"] = {"temperature": self._temperature}
        if image_b64 is not None:
            payload["images"] = [image_b64]

        headers = {"Authorization": f"Bearer {self._target.api_key}"} if self._target.api_key else {}
        try:
            resp = httpx.post(
                f"{self._target.base_url}/api/generate",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self._target.base_url}. "
                "Check that Ollama is running and VERDIKT_INFERENCE__OLLAMA_BASE_URL is correct."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            if status == 404:
                raise RuntimeError(
                    f"Model '{self._target.model}' not found in Ollama. "
                    f"Run 'ollama pull {self._target.model}' or choose a different model in the project settings."
                ) from exc
            if image_b64 and ("vision" in body.lower() or "multimodal" in body.lower() or "image" in body.lower()):
                raise RuntimeError(
                    f"Model '{self._target.model}' does not support image input. "
                    "Use a vision-capable model such as llava or llama3.2-vision for image projects."
                ) from exc
            raise RuntimeError(f"Ollama returned {status}: {body}") from exc

        data = resp.json()
        return (
            data.get("response", ""),
            data.get("prompt_eval_count", 0),
            data.get("eval_count", 0),
        )

    def _parse_response(self, raw: str, typical: dict[str, float]) -> tuple[dict[str, float], dict[str, str], str | None]:
        scores: dict[str, float] = {}
        explanations: dict[str, str] = {}
        data = self._extract_json(raw)
        if data is None:
            log.warning("LLMJudge: failed to parse JSON response, using typical scores")
            return dict(typical), {}, None

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

        description_raw = data.get("description")
        description = description_raw.strip() if isinstance(description_raw, str) and description_raw.strip() else None

        return scores, explanations, description

    @staticmethod
    def _weighted_average(scores: dict[str, float], weights: dict[str, float]) -> float:
        total_weight = sum(weights.get(k, 1.0) for k in scores)
        if total_weight == 0:
            return sum(scores.values()) / len(scores) if scores else 0.0
        return sum(v * weights.get(k, 1.0) for k, v in scores.items()) / total_weight
