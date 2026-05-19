from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

from verdikt.core.models import Chunk, DimensionProfile, PreferenceProfile, Project, Rating
from verdikt.inference.prompts import PROMPT_KEYS, load_prompts, render
from verdikt.inference.resolver import LLMTarget


_MAX_WORDS_PER_EXAMPLE = 400
_TOP_N = 5


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


class ProfileCrystalliser:
    def __init__(self, target: LLMTarget, prompts: dict[str, str] | None = None) -> None:
        self._target = target
        self._prompts = prompts or dict(PROMPT_KEYS)

    def crystallise(
        self,
        project: Project,
        ratings: list[Rating],
        chunks_by_id: dict[str, Chunk],
        current_version: int = 0,
        on_tokens: "Callable[[int, int], None] | None" = None,
    ) -> tuple[PreferenceProfile, int, int]:
        """Returns (profile, total_prompt_tokens, total_completion_tokens).

        on_tokens(prompt, completion) is called after each LLM call with running totals.
        """
        dimensions: list[DimensionProfile] = []
        total_prompt = 0
        total_completion = 0

        log.info("crystalliser: project=%s dims=%d ratings=%d provider=%s model=%s",
                 project.id, len(project.rating_dimensions), len(ratings),
                 self._target.provider, self._target.model)

        for dim in project.rating_dimensions:
            scored: list[tuple[float, str]] = []
            for r in ratings:
                if r.skipped:
                    continue
                score = r.dimension_scores.get(dim.name)
                if score is None:
                    continue
                chunk = chunks_by_id.get(r.chunk_id)
                if chunk is None:
                    continue
                if isinstance(chunk.content, str):
                    label = chunk.content
                elif chunk.description:
                    label = f"[image #{chunk.position + 1}: {chunk.description}]"
                else:
                    label = f"[image #{chunk.position + 1}]"
                scored.append((score, label))

            if not scored:
                dimensions.append(DimensionProfile(
                    name=dim.name,
                    description=dim.description,
                    summary="No ratings collected for this dimension yet.",
                    typical_score=0.0,
                ))
                continue

            typical_score = sum(s for s, _ in scored) / len(scored)
            scored.sort(key=lambda x: x[0])
            bottom = scored[:_TOP_N]
            top = scored[-_TOP_N:]
            score_range = scored[-1][0] - scored[0][0]

            is_image = any(label.startswith("[image") for _, label in scored)
            domain_hint = "images" if is_image else "text passages"

            examples_text = f"Highest-rated examples (scores {top[0][0]:.1f}–{top[-1][0]:.1f}):\n"
            for score, content in reversed(top):
                examples_text += f"  [{score:.1f}] {_truncate(content, _MAX_WORDS_PER_EXAMPLE)}\n\n"
            examples_text += f"Lowest-rated examples (scores {bottom[0][0]:.1f}–{bottom[-1][0]:.1f}):\n"
            for score, content in bottom:
                examples_text += f"  [{score:.1f}] {_truncate(content, _MAX_WORDS_PER_EXAMPLE)}\n\n"

            if score_range < 1.0:
                # Low variance: scores are clustered, no strong contrast to exploit
                contrast_instruction = (
                    f"Note: the scores are tightly clustered ({scored[0][0]:.1f}–{scored[-1][0]:.1f}), "
                    f"so there is little contrast between 'high' and 'low' here. "
                    f"Instead, describe the common properties shared across all examples that explain "
                    f"why this dimension scores {'consistently high' if typical_score >= 3.0 else 'consistently low'}."
                )
            else:
                contrast_instruction = (
                    "Compare the highest-rated and lowest-rated examples. "
                    "Identify the specific, concrete properties that are present in the high-scoring "
                    "examples but absent or reversed in the low-scoring ones."
                )

            prompt = render(
                self._prompts.get("prompt.crystalliser.dimension", PROMPT_KEYS["prompt.crystalliser.dimension"]),
                DOMAIN=domain_hint,
                DIM_NAME=dim.name,
                DIM_DESCRIPTION=dim.description,
                EXAMPLES=examples_text,
                CONTRAST_INSTRUCTION=contrast_instruction,
            )

            log.debug("crystalliser: calling LLM for dim '%s' (project=%s)", dim.name, project.id)
            raw, pt, ct = self._call_llm(prompt)
            total_prompt += pt
            total_completion += ct
            if on_tokens:
                on_tokens(total_prompt, total_completion)
            try:
                parsed = json.loads(raw)
                val = parsed.get("summary", "")
                summary = (val.strip() if isinstance(val, str) else "") or "Unable to generate summary."
            except (json.JSONDecodeError, ValueError):
                summary = raw.strip() or "Unable to generate summary."

            dimensions.append(DimensionProfile(
                name=dim.name,
                description=dim.description,
                summary=summary,
                typical_score=round(typical_score, 2),
            ))

        dimensions_list = "\n".join(
            f"- {d.name} (avg score {d.typical_score:.1f}/5): {d.summary}"
            for d in dimensions
        )
        overall_prompt = render(
            self._prompts.get("prompt.crystalliser.overall", PROMPT_KEYS["prompt.crystalliser.overall"]),
            DIM_COUNT=str(len(dimensions)),
            DIMENSIONS_LIST=dimensions_list,
        )
        overall_raw, opt, oct = self._call_llm(overall_prompt)
        total_prompt += opt
        total_completion += oct
        if on_tokens:
            on_tokens(total_prompt, total_completion)
        try:
            overall_parsed = json.loads(overall_raw)
            val = overall_parsed.get("summary", "")
            overall_summary = (val.strip() if isinstance(val, str) else "") or "Unable to generate summary."
        except (json.JSONDecodeError, ValueError):
            overall_summary = overall_raw.strip() or "Unable to generate summary."

        non_skipped = [r for r in ratings if not r.skipped]
        profile = PreferenceProfile(
            id=str(uuid.uuid4()),
            project_id=project.id,
            version=current_version + 1,
            dimensions=dimensions,
            overall_summary=overall_summary,
            rating_count=len(non_skipped),
            created_at=datetime.now(timezone.utc),
        )
        return profile, total_prompt, total_completion

    def _call_llm(self, prompt: str) -> tuple[str, int, int]:
        if self._target.provider in ("venice", "openrouter"):
            return self._call_openai_compat(prompt)
        return self._call_ollama(prompt)

    def _call_openai_compat(self, prompt: str) -> tuple[str, int, int]:
        try:
            resp = httpx.post(
                f"{self._target.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._target.api_key}"},
                json={
                    "model": self._target.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=120.0,
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

    def _call_ollama(self, prompt: str) -> tuple[str, int, int]:
        headers = {"Authorization": f"Bearer {self._target.api_key}"} if self._target.api_key else {}
        response = httpx.post(
            f"{self._target.base_url}/api/generate",
            json={"model": self._target.model, "prompt": prompt, "format": "json", "stream": False},
            headers=headers,
            timeout=120.0,
        )
        response.raise_for_status()
        rdata = response.json()
        return rdata.get("response", ""), rdata.get("prompt_eval_count", 0), rdata.get("eval_count", 0)
