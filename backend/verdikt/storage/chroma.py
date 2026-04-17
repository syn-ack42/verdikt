from __future__ import annotations

import chromadb

from verdikt.storage.base import VectorStore


class ChromaVectorStore(VectorStore):
    def __init__(self, client: chromadb.ClientAPI, collection_name: str) -> None:
        self._client = client
        self._collection = client.get_or_create_collection(collection_name)

    def upsert(self, item_id: str, embedding: list[float], metadata: dict) -> None:
        self._collection.upsert(
            ids=[item_id],
            embeddings=[embedding],
            metadatas=[metadata],
        )

    def query(self, embedding: list[float], n_results: int = 10) -> list[dict]:
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["metadatas", "distances"],
        )
        return [
            {"id": id_, "metadata": meta, "distance": dist}
            for id_, meta, dist in zip(
                result["ids"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]

    def delete_collection(self) -> None:
        self._client.delete_collection(self._collection.name)
