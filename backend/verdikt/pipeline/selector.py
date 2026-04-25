from __future__ import annotations

import random
import statistics
from collections import defaultdict

from verdikt.core.models import Chunk, Project
from verdikt.storage.base import ChunkStore, RatingStore


class RatingSelector:
    """Selects the next chunk to rate.

    Normal mode:
      - Before crystallisation_threshold ratings: diversity sampling (fewest-rated cluster first).
      - After threshold: uncertainty sampling (highest variance cluster first).
    Confirm AI mode: returns the unconfirmed AI-rated chunk with the highest avg score.
    """

    def __init__(
        self,
        chunk_store: ChunkStore,
        rating_store: RatingStore,
        confirm_ai_mode: bool = False,
        project: Project | None = None,
    ) -> None:
        self._chunks = chunk_store
        self._ratings = rating_store
        self._confirm_ai = confirm_ai_mode
        self._project = project

    def next_chunk(self, project_id: str) -> Chunk | None:
        if self._confirm_ai:
            return self._next_ai_confirm(project_id)

        if self._project is not None:
            rating_count = self._ratings.count_by_project(project_id)
            if rating_count >= self._project.crystallisation_threshold:
                result = self._next_uncertainty(project_id)
                if result is not None:
                    return result

        return self._next_diversity(project_id)

    def _next_ai_confirm(self, project_id: str) -> Chunk | None:
        unconfirmed = self._ratings.list_unconfirmed_ai(project_id)
        if not unconfirmed:
            return None
        top_rating = unconfirmed[0]
        return self._chunks.get(top_rating.chunk_id)

    def _next_uncertainty(self, project_id: str) -> Chunk | None:
        """Return a chunk from the cluster with the highest score variance (uncertainty sampling)."""
        all_chunks = self._chunks.list_by_project(project_id)
        clustered = [c for c in all_chunks if c.cluster_id is not None]
        if not clustered:
            return None

        human_rated = {
            r.chunk_id: r for r in self._ratings.list_by_project(project_id)
            if not r.is_ai and not r.skipped
        }
        unrated = [c for c in clustered if c.id not in human_rated]
        if not unrated:
            return None

        # Compute avg score per rated chunk
        avg_by_chunk: dict[str, float] = {}
        for chunk_id, r in human_rated.items():
            if r.dimension_scores:
                avg_by_chunk[chunk_id] = sum(r.dimension_scores.values()) / len(r.dimension_scores)

        # Group rated chunks by cluster and compute variance
        scores_by_cluster: dict[int, list[float]] = defaultdict(list)
        for c in clustered:
            if c.id in avg_by_chunk:
                scores_by_cluster[c.cluster_id].append(avg_by_chunk[c.id])

        # Build unrated pool grouped by cluster
        unrated_by_cluster: dict[int, list[Chunk]] = defaultdict(list)
        for chunk in unrated:
            unrated_by_cluster[chunk.cluster_id].append(chunk)

        if not unrated_by_cluster:
            return None

        # Rank clusters by variance (desc) among those that have unrated chunks
        def _variance(cluster_id: int) -> float:
            scores = scores_by_cluster.get(cluster_id, [])
            if len(scores) < 2:
                return 0.0
            return statistics.variance(scores)

        best_cluster = max(unrated_by_cluster.keys(), key=_variance)
        return random.choice(unrated_by_cluster[best_cluster])

    def _next_diversity(self, project_id: str) -> Chunk | None:
        all_chunks = self._chunks.list_by_project(project_id)
        clustered = [c for c in all_chunks if c.cluster_id is not None]
        if not clustered:
            return None

        human_rated_ids = {
            r.chunk_id for r in self._ratings.list_by_project(project_id)
            if not r.is_ai and not r.skipped
        }
        unrated = [c for c in clustered if c.id not in human_rated_ids]
        if not unrated:
            return None

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
