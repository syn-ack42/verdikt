from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx

from verdikt.core.models import Chunk, DimensionProfile, PreferenceProfile, Project, Rating
from verdikt.inference.resolver import LLMTarget


_MAX_WORDS_PER_EXAMPLE = 400
_TOP_N = 5


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


class ProfileCrystalliser:
    def __init__(self, target: LLMTarget) -> None:
        self._target = target

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
                else:
                    # Image chunk — use position as identifier; no text to show
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

            examples_text = "High-scoring examples (user enjoyed):\n"
            for score, content in reversed(top):
                examples_text += f"  [score {score:.1f}] {_truncate(content, _MAX_WORDS_PER_EXAMPLE)}\n\n"
            examples_text += "Low-scoring examples (user disliked):\n"
            for score, content in bottom:
                examples_text += f"  [score {score:.1f}] {_truncate(content, _MAX_WORDS_PER_EXAMPLE)}\n\n"

            domain_hint = "content" if any(
                label.startswith("[image") for _, label in scored
            ) else "text"
            prompt = (
                f"You are analysing a user's preferences for the dimension '{dim.name}': {dim.description}.\n\n"
                f"{examples_text}"
                f"Based on these ratings, write a concise preference summary (2-4 sentences) describing what this user "
                f"likes and dislikes about '{dim.name}' in {domain_hint}. Be specific and concrete. "
                f'Respond with a JSON object: {{"summary": "<your summary here>"}}'
            )

            raw, pt, ct = self._call_llm(prompt)
            total_prompt += pt
            total_completion += ct
            if on_tokens:
                on_tokens(total_prompt, total_completion)
            try:
                parsed = json.loads(raw)
                summary = parsed.get("summary", "").strip() or "Unable to generate summary."
            except (json.JSONDecodeError, ValueError):
                summary = raw.strip() or "Unable to generate summary."

            dimensions.append(DimensionProfile(
                name=dim.name,
                description=dim.description,
                summary=summary,
                typical_score=round(typical_score, 2),
            ))

        overall_prompt = (
            f"You are summarising a user's overall content preferences across {len(dimensions)} dimensions.\n\n"
            + "\n".join(
                f"- {d.name} (avg {d.typical_score:.1f}/5): {d.summary}"
                for d in dimensions
            )
            + "\n\nWrite a 3-5 sentence overall preference summary. "
            'Respond with a JSON object: {"summary": "<your summary here>"}'
        )
        overall_raw, opt, oct = self._call_llm(overall_prompt)
        total_prompt += opt
        total_completion += oct
        if on_tokens:
            on_tokens(total_prompt, total_completion)
        try:
            overall_parsed = json.loads(overall_raw)
            overall_summary = overall_parsed.get("summary", "").strip() or "Unable to generate summary."
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
        if self._target.provider == "venice":
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
            raise RuntimeError(f"Cannot reach Venice API at {self._target.base_url}.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:300]
            if status == 401:
                raise RuntimeError("Venice API key is invalid or expired.") from exc
            if status == 404:
                raise RuntimeError(
                    f"Model '{self._target.model}' not found on Venice. "
                    "Sync models and check the project's model setting."
                ) from exc
            raise RuntimeError(f"Venice API returned {status}: {body}") from exc

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)

    def _call_ollama(self, prompt: str) -> tuple[str, int, int]:
        response = httpx.post(
            f"{self._target.base_url}/api/generate",
            json={"model": self._target.model, "prompt": prompt, "format": "json", "stream": False},
            timeout=120.0,
        )
        response.raise_for_status()
        rdata = response.json()
        return rdata.get("response", ""), rdata.get("prompt_eval_count", 0), rdata.get("eval_count", 0)
