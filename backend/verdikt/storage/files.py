from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class StorageEntry:
    name: str
    path: str      # storage-relative, always uses / separator, rooted at /
    is_dir: bool
    size: int      # 0 for directories
    modified_at: datetime


class StorageBackend(ABC):
    @abstractmethod
    def list(self, path: str) -> list[StorageEntry]: ...

    @abstractmethod
    def resolve(self, path: str) -> Path:
        """Return the real filesystem path. Future S3 backend would download to a temp dir."""
        ...

    @abstractmethod
    def write(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    def mkdir(self, path: str) -> None: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def is_dir(self, path: str) -> bool: ...


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_resolve(self, path: str) -> Path:
        """Resolve a storage path to an absolute filesystem path, preventing traversal."""
        normalized = "/".join(
            part for part in path.replace("\\", "/").split("/")
            if part and part != ".."
        )
        resolved = (self._root / normalized).resolve()
        # Ensure the resolved path stays within the root
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(f"Path traversal attempt blocked: {path!r}")
        return resolved

    def list(self, path: str) -> list[StorageEntry]:
        target = self._safe_resolve(path)
        if not target.exists() or not target.is_dir():
            return []
        entries = []
        for entry in sorted(
            target.iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        ):
            try:
                stat = entry.stat()
            except OSError:
                continue
            storage_path = "/" + str(entry.relative_to(self._root)).replace(os.sep, "/")
            entries.append(StorageEntry(
                name=entry.name,
                path=storage_path,
                is_dir=entry.is_dir(),
                size=stat.st_size if entry.is_file() else 0,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            ))
        return entries

    def resolve(self, path: str) -> Path:
        return self._safe_resolve(path)

    def write(self, path: str, data: bytes) -> None:
        target = self._safe_resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def mkdir(self, path: str) -> None:
        self._safe_resolve(path).mkdir(parents=True, exist_ok=True)

    def delete(self, path: str) -> None:
        target = self._safe_resolve(path)
        if target == self._root:
            raise ValueError("Cannot delete storage root")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)

    def exists(self, path: str) -> bool:
        return self._safe_resolve(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._safe_resolve(path).is_dir()
