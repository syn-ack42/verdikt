from __future__ import annotations

import json
from typing import Callable

import httpx

from verdikt.core.models import Chunk, DiscoveryAnalysisResult, DiscoveryRating, DimensionProposal, Project


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
    def __init__(self, model: str, base_url: str) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

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
        prompt = (
            f"A user {label} this {medium}.{reason_block}"
            f"{content_block}\n\n"
            f"Describe the 2–3 most characteristic qualities of this {medium} that likely "
            f"drove the user's reaction. Focus on aesthetic, structural, and tonal qualities — "
            f"not plot summary or content description. Be specific and concrete.\n"
            f'Respond with JSON only: {{"qualities": "<your 2-3 sentence description>"}}'
        )

        payload: dict = {"model": self._model, "prompt": prompt, "format": "json", "stream": False}
        if image_b64:
            payload["images"] = [image_b64]

        try:
            response = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            rdata = response.json()
            pt = rdata.get("prompt_eval_count", 0)
            ct = rdata.get("eval_count", 0)
            raw = rdata.get("response", "")
            parsed = json.loads(raw)
            qualities = parsed.get("qualities", "").strip()
            return qualities, pt, ct
        except Exception:
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

        prompt = (
            f"You are helping a user discover what they care about in {domain_hint}. "
            f"Below are quality-descriptions of samples they reacted to strongly, "
            f"labelled by how much they liked or disliked each sample.\n\n"
            f"LIKED samples:\n{liked_block}\n\n"
            f"DISLIKED samples:\n{disliked_block}"
            f"{existing_block}\n\n"
            f"Based on the contrast between liked and disliked qualities, identify 3–6 rating "
            f"dimensions that capture what matters most to this user.\n\n"
            f"For each proposed dimension:\n"
            f"  - name: short label (2–4 words)\n"
            f"  - description: one sentence describing what a HIGH score means\n"
            f"  - weight: importance to this user "
            f"(0.5=weak signal, 1.0=normal, 1.5–2.0=consistently decisive)\n"
            f"  - is_new: true unless it clearly maps to an existing dimension by name\n"
            f"  - existing_name: the existing dimension name it replaces (or null)\n\n"
            f"Also list any existing dimensions whose qualities NEVER appeared in either liked "
            f"or disliked descriptions as irrelevant_existing.\n\n"
            f"Respond with JSON only:\n"
            f'{{"proposed_dimensions": [{{"name":"...","description":"...","weight":1.0,"is_new":true,"existing_name":null}}], '
            f'"irrelevant_existing": [], '
            f'"analysis_notes": "optional 1-2 sentence observation"}}'
        )

        try:
            response = httpx.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "format": "json", "stream": False},
                timeout=180.0,
            )
            response.raise_for_status()
            rdata = response.json()
            pt = rdata.get("prompt_eval_count", 0)
            ct = rdata.get("eval_count", 0)
            raw = rdata.get("response", "")
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
