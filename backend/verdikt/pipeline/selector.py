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
        meta = self._chunks.list_meta_by_project(project_id)
        clustered = [(cid, clid) for cid, clid in meta if clid is not None]
        if not clustered:
            return None

        human_scores = self._ratings.list_human_scores(project_id)
        unrated = [(cid, clid) for cid, clid in clustered if cid not in human_scores]
        if not unrated:
            return None

        scores_by_cluster: dict[int, list[float]] = defaultdict(list)
        for cid, clid in clustered:
            if cid in human_scores:
                scores_by_cluster[clid].append(human_scores[cid])

        unrated_by_cluster: dict[int, list[str]] = defaultdict(list)
        for cid, clid in unrated:
            unrated_by_cluster[clid].append(cid)

        if not unrated_by_cluster:
            return None

        def _variance(cluster_id: int) -> float:
            scores = scores_by_cluster.get(cluster_id, [])
            return statistics.variance(scores) if len(scores) >= 2 else 0.0

        best_cluster = max(unrated_by_cluster.keys(), key=_variance)
        return self._chunks.get(random.choice(unrated_by_cluster[best_cluster]))

    def _next_diversity(self, project_id: str) -> Chunk | None:
        meta = self._chunks.list_meta_by_project(project_id)
        clustered = [(cid, clid) for cid, clid in meta if clid is not None]
        if not clustered:
            return None

        human_rated_ids = self._ratings.get_human_rated_chunk_ids(project_id)
        unrated = [(cid, clid) for cid, clid in clustered if cid not in human_rated_ids]
        if not unrated:
            return None

        ratings_per_cluster: dict[int, int] = defaultdict(int)
        for cid, clid in clustered:
            if cid in human_rated_ids:
                ratings_per_cluster[clid] += 1

        unrated_by_cluster: dict[int, list[str]] = defaultdict(list)
        for cid, clid in unrated:
            unrated_by_cluster[clid].append(cid)

        min_rated = min(ratings_per_cluster.get(clid, 0) for _, clid in unrated)
        candidates_clusters = [
            clid for clid in unrated_by_cluster
            if ratings_per_cluster.get(clid, 0) == min_rated
        ]
        chosen_cluster = random.choice(candidates_clusters)
        return self._chunks.get(random.choice(unrated_by_cluster[chosen_cluster]))
