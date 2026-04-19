from __future__ import annotations

import random
from collections import defaultdict

from verdikt.core.models import Chunk
from verdikt.storage.base import ChunkStore, RatingStore


class RatingSelector:
    """Selects the next chunk to rate using cluster-based diversity sampling.

    Strategy: prioritise clusters that have the fewest existing ratings,
    breaking ties randomly. Returns None when all clustered chunks are rated.
    """

    def __init__(self, chunk_store: ChunkStore, rating_store: RatingStore) -> None:
        self._chunks = chunk_store
        self._ratings = rating_store

    def next_chunk(self, project_id: str) -> Chunk | None:
        all_chunks = self._chunks.list_by_project(project_id)
        clustered = [c for c in all_chunks if c.cluster_id is not None]
        if not clustered:
            return None

        rated_ids = {
            r.chunk_id for r in self._ratings.list_by_project(project_id)
        }
        unrated = [c for c in clustered if c.id not in rated_ids]
        if not unrated:
            return None

        # Count ratings per cluster across ALL chunks (rated or not)
        ratings_per_cluster: dict[int, int] = defaultdict(int)
        for chunk in clustered:
            if chunk.id in rated_ids:
                ratings_per_cluster[chunk.cluster_id] += 1

        # Group unrated chunks by cluster
        unrated_by_cluster: dict[int, list[Chunk]] = defaultdict(list)
        for chunk in unrated:
            unrated_by_cluster[chunk.cluster_id].append(chunk)

        # Pick cluster(s) with fewest ratings
        min_rated = min(ratings_per_cluster.get(cid, 0) for cid in unrated_by_cluster)
        candidates_clusters = [
            cid for cid in unrated_by_cluster
            if ratings_per_cluster.get(cid, 0) == min_rated
        ]
        chosen_cluster = random.choice(candidates_clusters)
        return random.choice(unrated_by_cluster[chosen_cluster])
