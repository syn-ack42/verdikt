from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx

from verdikt.core.models import Chunk, DimensionProfile, PreferenceProfile, Project, Rating


_MAX_WORDS_PER_EXAMPLE = 400
_TOP_N = 5


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


class ProfileCrystalliser:
    def __init__(self, ollama_base_url: str, model: str) -> None:
        self._base_url = ollama_base_url.rstrip("/")
        self._model = model

    def crystallise(
        self,
        project: Project,
        ratings: list[Rating],
        chunks_by_id: dict[str, Chunk],
        current_version: int = 0,
    ) -> tuple[PreferenceProfile, int, int]:
        """Returns (profile, total_prompt_tokens, total_completion_tokens)."""
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

            response = httpx.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "format": "json", "stream": False},
                timeout=120.0,
            )
            response.raise_for_status()
            rdata = response.json()
            total_prompt += rdata.get("prompt_eval_count", 0)
            total_completion += rdata.get("eval_count", 0)
            raw = rdata["response"]
            parsed = json.loads(raw)
            summary = parsed.get("summary", "").strip() or "Unable to generate summary."

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
        overall_response = httpx.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": overall_prompt, "format": "json", "stream": False},
            timeout=120.0,
        )
        overall_response.raise_for_status()
        ordata = overall_response.json()
        total_prompt += ordata.get("prompt_eval_count", 0)
        total_completion += ordata.get("eval_count", 0)
        overall_raw = ordata["response"]
        overall_parsed = json.loads(overall_raw)
        overall_summary = overall_parsed.get("summary", "").strip() or "Unable to generate summary."

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
