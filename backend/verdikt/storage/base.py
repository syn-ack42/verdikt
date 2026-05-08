from abc import ABC, abstractmethod

from verdikt.core.models import Chunk, MaterialItem, PipelinePhase, PluginConfig, PreferenceProfile, Project, Rating


class ProjectStore(ABC):
    @abstractmethod
    def create(self, project: Project) -> Project: ...

    @abstractmethod
    def get(self, project_id: str) -> Project | None: ...

    @abstractmethod
    def get_by_name(self, name: str) -> list[Project]: ...

    @abstractmethod
    def list_all(self) -> list[Project]: ...

    @abstractmethod
    def delete(self, project_id: str) -> None: ...


class MaterialStore(ABC):
    @abstractmethod
    def save(self, item: MaterialItem) -> MaterialItem: ...

    @abstractmethod
    def get(self, item_id: str) -> MaterialItem | None: ...

    @abstractmethod
    def list_by_project(
        self,
        project_id: str,
        phase: PipelinePhase | None = None,
    ) -> list[MaterialItem]: ...

    @abstractmethod
    def update_phase(self, item_id: str, phase: PipelinePhase) -> None: ...

    @abstractmethod
    def get_by_source(self, project_id: str, source_plugin: str, source_path: str) -> MaterialItem | None: ...

    @abstractmethod
    def update_content(self, item_id: str, content: bytes | str, content_hash: str | None) -> None:
        """Replace content and reset pipeline phase to INGESTED."""
        ...

    @abstractmethod
    def update_plugin_metadata(self, item_id: str, plugin_metadata: dict) -> None:
        """Overwrite plugin_metadata without touching content or pipeline phase."""
        ...

    @abstractmethod
    def get_by_source_path(self, project_id: str, source_path: str) -> MaterialItem | None: ...

    @abstractmethod
    def get_by_seq(self, project_id: str, seq: int) -> MaterialItem | None: ...

    @abstractmethod
    def list_by_source_plugin(self, project_id: str, source_plugin: str) -> list[MaterialItem]: ...

    @abstractmethod
    def delete(self, item_id: str) -> None: ...


class ChunkStore(ABC):
    @abstractmethod
    def save_many(self, chunks: list[Chunk]) -> list[Chunk]: ...

    @abstractmethod
    def list_by_material(self, material_item_id: str) -> list[Chunk]: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[Chunk]: ...

    @abstractmethod
    def update_cluster(self, chunk_id: str, cluster_id: int) -> None: ...

    def bulk_update_clusters(self, id_to_cluster: dict[str, int]) -> None:
        """Update cluster_id for many chunks at once. Default: loop over update_cluster."""
        for cid, label in id_to_cluster.items():
            self.update_cluster(cid, label)

    @abstractmethod
    def delete_by_material(self, material_item_id: str) -> None: ...

    @abstractmethod
    def update_description(self, chunk_id: str, description: str) -> None: ...

    def count_by_project(self, project_id: str) -> int:
        return len(self.list_by_project(project_id))

    def list_meta_by_project(self, project_id: str) -> list[tuple[str, int | None]]:
        """Return (chunk_id, cluster_id) without loading content bytes.

        Override in concrete stores for efficiency — the default falls back to
        list_by_project which loads all content.
        """
        return [(c.id, c.cluster_id) for c in self.list_by_project(project_id)]

    def cluster_stats(self, project_id: str, human_rated_ids: set[str]) -> dict[int, tuple[int, int]]:
        """Return {cluster_id: (human_rated_count, total_count)}.

        Default: O(n) scan via list_meta_by_project. Override for a single SQL join.
        """
        result: dict[int, tuple[int, int]] = {}
        for cid, clid in self.list_meta_by_project(project_id):
            if clid is None:
                continue
            rated, total = result.get(clid, (0, 0))
            result[clid] = (rated + (1 if cid in human_rated_ids else 0), total + 1)
        return result

    def cluster_ids_for_chunks(self, project_id: str, chunk_ids: list[str]) -> dict[str, int | None]:
        """Return {chunk_id: cluster_id} for a set of chunk IDs.

        Default: scans via list_meta_by_project. Override for a targeted SQL IN query.
        """
        if not chunk_ids:
            return {}
        target = set(chunk_ids)
        return {cid: clid for cid, clid in self.list_meta_by_project(project_id) if cid in target}

    def random_unrated_in_cluster(self, project_id: str, cluster_id: int, human_rated_ids: set[str]) -> str | None:
        """Return a random unrated chunk_id from the given cluster.

        Default: O(n) scan via list_meta_by_project. Override for a SQL RANDOM() query.
        """
        import random
        candidates = [
            cid for cid, clid in self.list_meta_by_project(project_id)
            if clid == cluster_id and cid not in human_rated_ids
        ]
        return random.choice(candidates) if candidates else None


class VectorStore(ABC):
    @abstractmethod
    def upsert(
        self,
        item_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None: ...

    @abstractmethod
    def query(
        self,
        embedding: list[float],
        n_results: int = 10,
    ) -> list[dict]: ...

    @abstractmethod
    def delete_collection(self) -> None: ...

    @abstractmethod
    def delete_items(self, ids: list[str]) -> None: ...

    @abstractmethod
    def get_all_embeddings(self) -> tuple[list[str], "np.ndarray"]:
        """Return (ids, embeddings) for every item in the collection.

        Used by the cluster phase to retrieve stored embeddings without
        re-loading content bytes from the database.
        """
        ...


class RatingStore(ABC):
    @abstractmethod
    def save(self, rating: Rating) -> Rating: ...

    @abstractmethod
    def get(self, rating_id: str) -> Rating | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[Rating]: ...

    @abstractmethod
    def list_by_chunk(self, chunk_id: str) -> list[Rating]: ...

    @abstractmethod
    def count_by_project(self, project_id: str) -> int: ...

    @abstractmethod
    def delete_by_material(self, material_item_id: str) -> None: ...

    @abstractmethod
    def list_unconfirmed_ai(self, project_id: str) -> list[Rating]:
        """AI-generated ratings not yet confirmed by a human, ordered by avg score desc."""
        ...

    @abstractmethod
    def get_all_rated_chunk_ids(self, project_id: str) -> set[str]:
        """Chunk IDs that have any rating (human or AI)."""
        ...

    @abstractmethod
    def count_skipped(self, project_id: str) -> int:
        """Number of skipped ratings for a project."""
        ...

    @abstractmethod
    def count_by_type(self, project_id: str) -> dict:
        """Returns {"human": n, "ai": n} counts for non-skipped ratings."""
        ...

    def get_human_rated_chunk_ids(self, project_id: str) -> set[str]:
        """Chunk IDs with a human (non-AI, non-skipped) rating."""
        return {r.chunk_id for r in self.list_by_project(project_id) if not r.is_ai and not r.skipped}

    def get_complete_human_rated_chunk_ids(self, project_id: str, dim_names: set[str]) -> set[str]:
        """Chunk IDs where the human rating covers all of dim_names."""
        result: set[str] = set()
        for r in self.list_by_project(project_id):
            if r.is_ai or r.skipped:
                continue
            if dim_names.issubset(r.dimension_scores.keys()):
                result.add(r.chunk_id)
        return result

    def list_human_scores(self, project_id: str) -> dict[str, float]:
        """Return {chunk_id: avg_dimension_score} for human non-skipped ratings only.

        Override in concrete stores to avoid loading full Rating objects.
        """
        result: dict[str, float] = {}
        for r in self.list_by_project(project_id):
            if not r.is_ai and not r.skipped and r.dimension_scores:
                result[r.chunk_id] = sum(r.dimension_scores.values()) / len(r.dimension_scores)
        return result


class ProfileStore(ABC):
    @abstractmethod
    def save(self, profile: PreferenceProfile) -> PreferenceProfile: ...

    @abstractmethod
    def get_latest(self, project_id: str) -> PreferenceProfile | None: ...

    @abstractmethod
    def list_versions(self, project_id: str) -> list[PreferenceProfile]: ...

    @abstractmethod
    def update(self, profile: PreferenceProfile) -> PreferenceProfile: ...


class PluginConfigStore(ABC):
    @abstractmethod
    def save(self, cfg: PluginConfig) -> PluginConfig: ...

    @abstractmethod
    def get(self, project_id: str, plugin_name: str) -> PluginConfig | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[PluginConfig]: ...

    @abstractmethod
    def delete(self, project_id: str, plugin_name: str) -> None: ...
