from abc import ABC, abstractmethod

from verdikt.core.models import Chunk, MaterialItem, PipelinePhase, Project


class ProjectStore(ABC):
    @abstractmethod
    def create(self, project: Project) -> Project: ...

    @abstractmethod
    def get(self, project_id: str) -> Project | None: ...

    @abstractmethod
    def list_all(self) -> list[Project]: ...


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


class ChunkStore(ABC):
    @abstractmethod
    def save_many(self, chunks: list[Chunk]) -> list[Chunk]: ...

    @abstractmethod
    def list_by_material(self, material_item_id: str) -> list[Chunk]: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[Chunk]: ...

    @abstractmethod
    def update_cluster(self, chunk_id: str, cluster_id: int) -> None: ...


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
