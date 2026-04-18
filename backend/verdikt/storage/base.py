from abc import ABC, abstractmethod

from verdikt.core.models import Chunk, MaterialItem, PipelinePhase, Project


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
    def get_by_source_path(self, project_id: str, source_path: str) -> MaterialItem | None: ...

    @abstractmethod
    def get_by_seq(self, project_id: str, seq: int) -> MaterialItem | None: ...

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

    @abstractmethod
    def delete_by_material(self, material_item_id: str) -> None: ...


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
