from __future__ import annotations

import json
import random
from collections import defaultdict

from verdikt.core.models import Chunk
from verdikt.storage.base import ChunkStore, RatingStore


class RatingSelector:
    """Selects the next chunk to rate.

    Normal mode: cluster-based diversity sampling (fewest-rated cluster first).
    Confirm AI mode: returns the unconfirmed AI-rated chunk with the highest avg score.
    """

    def __init__(
        self,
        chunk_store: ChunkStore,
        rating_store: RatingStore,
        confirm_ai_mode: bool = False,
    ) -> None:
        self._chunks = chunk_store
        self._ratings = rating_store
        self._confirm_ai = confirm_ai_mode

    def next_chunk(self, project_id: str) -> Chunk | None:
        if self._confirm_ai:
            return self._next_ai_confirm(project_id)
        return self._next_diversity(project_id)

    def _next_ai_confirm(self, project_id: str) -> Chunk | None:
        unconfirmed = self._ratings.list_unconfirmed_ai(project_id)
        if not unconfirmed:
            return None
        # list_unconfirmed_ai returns highest avg score first
        top_rating = unconfirmed[0]
        return self._chunks.get(top_rating.chunk_id)

    def _next_diversity(self, project_id: str) -> Chunk | None:
        all_chunks = self._chunks.list_by_project(project_id)
        clustered = [c for c in all_chunks if c.cluster_id is not None]
        if not clustered:
            return None

        # Exclude chunks that already have a human rating (is_ai=False, not skipped)
        human_rated_ids = {
            r.chunk_id for r in self._ratings.list_by_project(project_id)
            if not r.is_ai and not r.skipped
        }
        unrated = [c for c in clustered if c.id not in human_rated_ids]
        if not unrated:
            return None

        # Count human ratings per cluster
        ratings_per_cluster: dict[int, int] = defaultdict(int)
        for chunk in clustered:
            if chunk.id in human_rated_ids:
                ratings_per_cluster[chunk.cluster_id] += 1

        unrated_by_cluster: dict[int, list[Chunk]] = defaultdict(list)
        for chunk in unrated:
            unrated_by_cluster[chunk.cluster_id].append(chunk)

        min_rated = min(ratings_per_cluster.get(cid, 0) for cid in unrated_by_cluster)
        candidates_clusters = [
            cid for cid in unrated_by_cluster
            if ratings_per_cluster.get(cid, 0) == min_rated
        ]
        chosen_cluster = random.choice(candidates_clusters)
        return random.choice(unrated_by_cluster[chosen_cluster])
