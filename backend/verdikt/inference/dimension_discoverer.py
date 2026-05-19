from __future__ import annotations

import json
from typing import Callable

import httpx

from verdikt.core.models import Chunk, DiscoveryAnalysisResult, DiscoveryRating, DimensionProposal, Project
from verdikt.inference.prompts import PROMPT_KEYS, load_prompts, render
from verdikt.inference.resolver import LLMTarget


_MAX_WORDS = 300


def _truncate(text: str, max_words: int = _MAX_WORDS) -> str:
    words = text.split()
    return " ".join(words[:max_words]) + " …" if len(words) > max_words else text


def _preference_label(preference: float) -> str:
    abs_p = abs(preference)
    direction = "prefers" if preference > 0 else "avoids"
    if abs_p >= 1.8:
        return f"strongly {direction}"
    if abs_p >= 1.0:
        return direction
    return f"slightly {direction}"


class DimensionDiscoverer:
    def __init__(self, target: LLMTarget, prompts: dict[str, str] | None = None) -> None:
        self._target = target
        self._prompts = prompts or dict(PROMPT_KEYS)

    def analyse(
        self,
        project: Project,
        discovery_ratings: list[DiscoveryRating],
        chunks_by_id: dict[str, Chunk],
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> tuple[DiscoveryAnalysisResult, int, int]:
        """Two-stage analysis: describe each chunk's qualities, then extract dimensions.

        Returns (result, total_prompt_tokens, total_completion_tokens).
        on_progress(phase, done, total) is called after each LLM call.
        """
        total_prompt = 0
        total_completion = 0

        # Stage 1 — describe characteristic qualities for each non-neutral rating
        active = [dr for dr in discovery_ratings if abs(dr.preference) >= 0.5]
        descriptions: list[tuple[float, str]] = []  # (preference, qualities_text)

        for i, dr in enumerate(active):
            chunk = chunks_by_id.get(dr.chunk_id)
            if chunk is None:
                continue
            qualities, pt, ct = self._describe_chunk(chunk, dr, project.domain)
            total_prompt += pt
            total_completion += ct
            if qualities:
                descriptions.append((dr.preference, qualities))
            if on_progress:
                on_progress("describing", i + 1, len(active))

        # Stage 2 — synthesise dimensions from quality descriptions
        if on_progress:
            on_progress("synthesising", 0, 1)
        result, pt, ct = self._extract_dimensions(descriptions, project)
        total_prompt += pt
        total_completion += ct
        if on_progress:
            on_progress("synthesising", 1, 1)

        return result, total_prompt, total_completion

    def _describe_chunk(
        self, chunk: Chunk, dr: DiscoveryRating, domain: str
    ) -> tuple[str, int, int]:
        label = _preference_label(dr.preference)
        is_image = isinstance(chunk.content, bytes)
        medium = "image" if is_image else "text passage"

        if is_image:
            content_block = ""
            image_b64 = None
            import base64
            image_b64 = base64.b64encode(chunk.content).decode()
        else:
            content_repr = _truncate(chunk.content)  # type: ignore[arg-type]
            content_block = f"\n\nPassage:\n{content_repr}"
            image_b64 = None

        reason_block = f' The user said: "{dr.reason}".' if dr.reason else ""
        prompt = render(
            self._prompts.get("prompt.discoverer.qualities", PROMPT_KEYS["prompt.discoverer.qualities"]),
            LABEL=label,
            MEDIUM=medium,
            REASON_BLOCK=reason_block,
            CONTENT_BLOCK=content_block,
        )

        try:
            raw, pt, ct = self._call_llm(prompt, image_b64)
            parsed = json.loads(raw)
            qualities = parsed.get("qualities", "").strip()
            return qualities, pt, ct
        except RuntimeError:
            # API/network errors (key invalid, model not found, etc.) — let them propagate
            raise
        except Exception:
            # JSON parse errors or unexpected response shape — skip this chunk
            return "", 0, 0

    def _extract_dimensions(
        self,
        descriptions: list[tuple[float, str]],
        project: Project,
    ) -> tuple[DiscoveryAnalysisResult, int, int]:
        liked = sorted([(p, q) for p, q in descriptions if p > 0], key=lambda x: -x[0])
        disliked = sorted([(p, q) for p, q in descriptions if p < 0], key=lambda x: x[0])

        liked_block = "\n".join(
            f"  [{_preference_label(p)}] {q}" for p, q in liked
        ) or "  (none)"
        disliked_block = "\n".join(
            f"  [{_preference_label(p)}] {q}" for p, q in disliked
        ) or "  (none)"

        existing_block = ""
        if project.rating_dimensions:
            existing_block = "\n\nExisting rating dimensions (already defined for this project):\n" + "\n".join(
                f"  - {d.name}: {d.description}" for d in project.rating_dimensions
            )

        domain_hint = "images" if project.domain == "image" else "text content"

        prompt = render(
            self._prompts.get("prompt.discoverer.dimensions", PROMPT_KEYS["prompt.discoverer.dimensions"]),
            DOMAIN=domain_hint,
            LIKED_BLOCK=liked_block,
            DISLIKED_BLOCK=disliked_block,
            EXISTING_BLOCK=existing_block,
        )

        try:
            raw, pt, ct = self._call_llm(prompt)
            parsed = json.loads(raw)

            proposals = [
                DimensionProposal(
                    name=d.get("name", "").strip(),
                    description=d.get("description", "").strip(),
                    weight=float(d.get("weight", 1.0)),
                    is_new=bool(d.get("is_new", True)),
                    existing_name=d.get("existing_name") or None,
                )
                for d in parsed.get("proposed_dimensions", [])
                if d.get("name", "").strip()
            ]
            irrelevant = [
                str(n) for n in parsed.get("irrelevant_existing", []) if n
            ]
            notes = (parsed.get("analysis_notes") or "").strip() or None

            return DiscoveryAnalysisResult(
                proposed_dimensions=proposals,
                irrelevant_existing=irrelevant,
                analysis_notes=notes,
            ), pt, ct

        except Exception as exc:
            raise RuntimeError(
                "Analysis failed — LLM could not be reached or returned unparseable output."
            ) from exc

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
                timeout=180.0,
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

    def _call_ollama(self, prompt: str, image_b64: str | None = None) -> tuple[str, int, int]:
        payload: dict = {"model": self._target.model, "prompt": prompt, "format": "json", "stream": False}
        if image_b64:
            payload["images"] = [image_b64]

        headers = {"Authorization": f"Bearer {self._target.api_key}"} if self._target.api_key else {}
        try:
            response = httpx.post(
                f"{self._target.base_url}/api/generate",
                json=payload,
                headers=headers,
                timeout=180.0,
            )
            response.raise_for_status()
            rdata = response.json()
            pt = rdata.get("prompt_eval_count", 0)
            ct = rdata.get("eval_count", 0)
            raw = rdata.get("response", "")
            return raw, pt, ct
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self._target.base_url}. "
                "Check that Ollama is running and VERDIKT_INFERENCE__OLLAMA_BASE_URL is correct."
            ) from exc
