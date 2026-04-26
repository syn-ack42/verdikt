from __future__ import annotations

import logging
import random
from collections import deque
from collections.abc import Iterator
from datetime import datetime, timezone

from verdikt.core.models import Domain, PreferenceProfile, Project, Rating
from verdikt.inference.base import EmbedderBase
from verdikt.inference.judge import LLMJudge
from verdikt.storage.base import ChunkStore, MaterialStore, RatingStore, VectorStore

log = logging.getLogger(__name__)

_STOP_FLAG = object()  # sentinel for cooperative stop


class AIRater:
    """Background worker that automatically rates unrated chunks using the LLM judge.

    Two-phase operation:
    1. Re-score any unconfirmed AI ratings using the current profile.
    2. Score new unrated chunks in batches, prioritising embedding similarity to
       the profile summary and stopping when batch averages consistently decline.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: EmbedderBase,
        judge: LLMJudge,
        chunk_store: ChunkStore,
        rating_store: RatingStore,
        material_store: MaterialStore,
    ) -> None:
        self._vs = vector_store
        self._embedder = embedder
        self._judge = judge
        self._chunks = chunk_store
        self._ratings = rating_store
        self._materials = material_store

    def run(
        self,
        project: Project,
        profile: PreferenceProfile,
        stop_flag: list,  # mutable list; append _STOP_FLAG to request stop
        batch_size: int = 20,
        random_fraction: float = 0.2,
        stop_window: int = 3,
        stop_threshold: float = 2.5,
    ) -> Iterator[dict]:
        """Score chunks and yield status events.

        Event types:
        - ``start``       — ``{type, profile_version}``
        - ``rescore``     — ``{type, chunk_id, current, total}`` (phase 1)
        - ``progress``    — ``{type, chunk_id, overall_score, batch, current, total}``
        - ``batch_done``  — ``{type, batch, avg, total_rated}``
        - ``stopped``     — ``{type, reason, total_rated}`` reason: "user_stopped" | "diminishing_returns"
        - ``complete``    — ``{type, total_rated}`` (pool exhausted)
        """
        project_id = project.id
        yield {"type": "start", "profile_version": profile.version}

        # Phase 1: re-score unconfirmed AI ratings with the current profile
        unconfirmed = self._ratings.list_unconfirmed_ai(project_id)
        total_unconfirmed = len(unconfirmed)
        if total_unconfirmed > 0:
            log.info("ai_rater: re-scoring %d unconfirmed AI ratings", total_unconfirmed)
        for i, existing_rating in enumerate(unconfirmed):
            if stop_flag:
                yield {"type": "stopped", "reason": "user_stopped", "total_rated": i}
                return
            chunk = self._chunks.get(existing_rating.chunk_id)
            if chunk is None:
                continue
            try:
                scores, _, _expl = self._judge.score_chunk(chunk.content, profile, project)
                self._ratings.update_ai_scores(existing_rating.id, scores)
            except Exception:
                log.exception("ai_rater: failed to re-score chunk %s", existing_rating.chunk_id)
            yield {"type": "rescore", "chunk_id": existing_rating.chunk_id, "current": i + 1, "total": total_unconfirmed}

        # Phase 2: score new unrated chunks in batches
        rated_ids = self._ratings.get_all_rated_chunk_ids(project_id)

        all_chunks = self._chunks.list_by_project(project_id)
        unrated_chunks = [c for c in all_chunks if c.id not in rated_ids]

        if not unrated_chunks:
            yield {"type": "complete", "total_rated": len(rated_ids)}
            return

        # Get similarity-ordered candidates from vector store.
        # Image projects use CLIP (bytes-only), so text-embedding the profile summary is
        # not possible; fall back to random ordering silently.
        n_query = min(len(unrated_chunks), 500)
        is_image = getattr(project.domain, "value", project.domain) == Domain.IMAGE.value
        similar_ids: list[str] = []
        if not is_image:
            try:
                raw_emb = self._embedder.embed([profile.overall_summary])[0]
                embedding = raw_emb.tolist() if hasattr(raw_emb, "tolist") else list(raw_emb)
                similar_results = self._vs.query(embedding, n_results=n_query)
                similar_ids = [r["id"] for r in similar_results if r["id"] not in rated_ids]
            except Exception:
                log.warning("ai_rater: vector store query failed, using random order")
        else:
            log.debug("ai_rater: image project — skipping text similarity, using random order")

        similar_set = set(similar_ids)
        unrated_by_id = {c.id: c for c in unrated_chunks}

        # Build ordered pool: similarity-ranked first, then remaining
        ordered_pool = [cid for cid in similar_ids if cid in unrated_by_id]
        random_pool = [c.id for c in unrated_chunks if c.id not in similar_set]
        random.shuffle(random_pool)

        batch_avgs: deque[float] = deque(maxlen=stop_window)
        total_rated = 0
        batch_num = 0
        pool_pos = 0

        while True:
            if stop_flag:
                yield {"type": "stopped", "reason": "user_stopped", "total_rated": total_rated}
                return

            # Assemble next batch
            n_similar = max(1, int(batch_size * (1 - random_fraction)))
            n_random = batch_size - n_similar

            batch_ids: list[str] = []
            while len(batch_ids) < n_similar and pool_pos < len(ordered_pool):
                cid = ordered_pool[pool_pos]
                pool_pos += 1
                if cid not in rated_ids:
                    batch_ids.append(cid)

            # Fill remainder from random pool, deduplicating against already-seen ids
            random_taken = 0
            random_pool = [cid for cid in random_pool if cid not in rated_ids and cid not in batch_ids]
            for cid in random_pool[:n_random]:
                batch_ids.append(cid)
                random_taken += 1
            random_pool = random_pool[random_taken:]

            if not batch_ids:
                yield {"type": "complete", "total_rated": total_rated}
                return

            batch_num += 1
            batch_scores: list[float] = []

            for i, chunk_id in enumerate(batch_ids):
                if stop_flag:
                    yield {"type": "stopped", "reason": "user_stopped", "total_rated": total_rated}
                    return

                chunk = unrated_by_id.get(chunk_id)
                if chunk is None:
                    continue

                try:
                    scores, overall, explanations = self._judge.score_chunk(chunk.content, profile, project)
                except Exception:
                    log.exception("ai_rater: judge failed for chunk %s", chunk_id)
                    continue

                rating = Rating(
                    project_id=project_id,
                    chunk_id=chunk_id,
                    material_item_id=chunk.material_item_id,
                    dimension_scores=scores,
                    is_ai=True,
                    explanations=explanations,
                    rated_at=datetime.now(timezone.utc),
                )
                self._ratings.save(rating)
                rated_ids.add(chunk_id)
                total_rated += 1
                batch_scores.append(overall)

                yield {
                    "type": "progress",
                    "chunk_id": chunk_id,
                    "overall_score": round(overall, 3),
                    "batch": batch_num,
                    "current": i + 1,
                    "total": len(batch_ids),
                }

            if batch_scores:
                batch_avg = sum(batch_scores) / len(batch_scores)
            else:
                batch_avg = 0.0

            batch_avgs.append(batch_avg)
            yield {"type": "batch_done", "batch": batch_num, "avg": round(batch_avg, 3), "total_rated": total_rated}

            # Stop condition: stop_window consecutive declining batches all below threshold
            if len(batch_avgs) >= stop_window:
                avgs = list(batch_avgs)
                declining = all(avgs[i] > avgs[i + 1] for i in range(len(avgs) - 1))
                if declining and avgs[-1] < stop_threshold:
                    log.info(
                        "ai_rater: stopping — %d consecutive declining batches, last avg %.2f < %.2f",
                        stop_window, avgs[-1], stop_threshold,
                    )
                    yield {"type": "stopped", "reason": "diminishing_returns", "total_rated": total_rated}
                    return
