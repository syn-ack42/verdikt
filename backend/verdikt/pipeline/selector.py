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
        human_scores = self._ratings.list_human_scores(project_id)
        if not human_scores:
            return None

        stats = self._chunks.cluster_stats(project_id, set(human_scores.keys()))
        # clusters that have at least one unrated chunk
        clusters_with_unrated = {cid for cid, (rated, total) in stats.items() if rated < total}
        if not clusters_with_unrated:
            return None

        # map rated chunk → cluster using a targeted query on the small rated set
        cid_to_cluster = self._chunks.cluster_ids_for_chunks(project_id, list(human_scores.keys()))

        scores_by_cluster: dict[int, list[float]] = defaultdict(list)
        for cid, score in human_scores.items():
            clid = cid_to_cluster.get(cid)
            if clid is not None and clid in clusters_with_unrated:
                scores_by_cluster[clid].append(score)

        def _variance(cluster_id: int) -> float:
            scores = scores_by_cluster.get(cluster_id, [])
            return statistics.variance(scores) if len(scores) >= 2 else 0.0

        best_cluster = max(clusters_with_unrated, key=_variance)
        human_rated_ids = set(human_scores.keys())
        chunk_id = self._chunks.random_unrated_in_cluster(project_id, best_cluster, human_rated_ids)
        return self._chunks.get(chunk_id) if chunk_id else None

    def _next_diversity(self, project_id: str) -> Chunk | None:
        if self._project and self._project.rating_dimensions:
            dim_names = {d.name for d in self._project.rating_dimensions}
            human_rated_ids = self._ratings.get_complete_human_rated_chunk_ids(project_id, dim_names)
        else:
            human_rated_ids = self._ratings.get_human_rated_chunk_ids(project_id)
        stats = self._chunks.cluster_stats(project_id, human_rated_ids)

        # clusters that have unrated chunks (rated < total per the ratings table)
        clusters_with_unrated = {cid: rated for cid, (rated, total) in stats.items() if rated < total}
        if not clusters_with_unrated:
            return None

        min_rated = min(clusters_with_unrated.values())
        # Prefer least-rated clusters; shuffle so ties are broken randomly
        priority = [cid for cid, rated in clusters_with_unrated.items() if rated == min_rated]
        rest = [cid for cid, rated in clusters_with_unrated.items() if rated > min_rated]
        random.shuffle(priority)
        random.shuffle(rest)

        # Try priority clusters first, then fall back to the rest.
        # A cluster that looks "unrated" in the ratings table may still be fully
        # covered by human_rated_ids from a separate table (e.g. discovery_ratings),
        # so we must retry rather than returning None on the first miss.
        for cid in priority + rest:
            chunk_id = self._chunks.random_unrated_in_cluster(project_id, cid, human_rated_ids)
            if chunk_id:
                return self._chunks.get(chunk_id)
        return None
