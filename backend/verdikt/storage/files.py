from __future__ import annotations

import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)

_NONCE_LEN = 12


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
        """Return a readable filesystem path for the entry.

        For encrypted backends this writes a decrypted temp file; callers must
        not hold the path beyond the request lifecycle (cleanup() removes temps).
        Resolving "/" always returns the storage root for path-construction purposes.
        """
        ...

    @abstractmethod
    def read(self, path: str) -> bytes: ...

    @abstractmethod
    def stat(self, path: str) -> StorageEntry | None: ...

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

    def cleanup(self) -> None:
        """Remove any temp files created by resolve(). Called at end of request."""


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_resolve(self, path: str) -> Path:
        normalized = "/".join(
            part for part in path.replace("\\", "/").split("/")
            if part and part != ".."
        )
        resolved = (self._root / normalized).resolve()
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

    def read(self, path: str) -> bytes:
        return self._safe_resolve(path).read_bytes()

    def stat(self, path: str) -> StorageEntry | None:
        target = self._safe_resolve(path)
        if not target.exists():
            return None
        try:
            st = target.stat()
        except OSError:
            return None
        storage_path = "/" + str(target.relative_to(self._root)).replace(os.sep, "/") if target != self._root else "/"
        return StorageEntry(
            name=target.name,
            path=storage_path,
            is_dir=target.is_dir(),
            size=st.st_size if target.is_file() else 0,
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        )

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


class EncryptedStorageBackend(StorageBackend):
    """Files stored as AES-256-GCM encrypted blobs named by UUID.

    Virtual directory structure is tracked in the file_manifest table of the
    per-user SQLCipher database. On-disk names contain no original filename or
    extension — the manifest (itself encrypted) is the only place that knows them.

    Key: 32 bytes derived from the user's db_key via HKDF-SHA256 with a
    distinct info tag so it's separate from the database encryption key.
    """

    def __init__(self, root: Path, key: bytes, session: object) -> None:
        from sqlalchemy.orm import Session as _Session
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._key = key  # 32-byte AES-256-GCM key
        self._session: _Session = session  # type: ignore[assignment]
        self._temp_files: list[str] = []

    # ── Crypto ─────────────────────────────────────────────────────────────────

    def _encrypt(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(_NONCE_LEN)
        return nonce + AESGCM(self._key).encrypt(nonce, data, None)

    def _decrypt(self, blob: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(self._key).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None)

    # ── Path helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(path: str) -> str:
        parts = [p for p in path.replace("\\", "/").split("/") if p and p != ".."]
        return ("/" + "/".join(parts)) if parts else "/"

    def _row(self, norm: str):
        from sqlalchemy import select
        from verdikt.storage.orm import FileManifestRow
        return self._session.execute(
            select(FileManifestRow).where(FileManifestRow.user_path == norm)
        ).scalar_one_or_none()

    # ── StorageBackend interface ────────────────────────────────────────────────

    def list(self, path: str) -> list[StorageEntry]:
        from sqlalchemy import select
        from verdikt.storage.orm import FileManifestRow

        norm = self._normalize(path)
        prefix = (norm + "/") if norm != "/" else "/"

        rows = self._session.execute(select(FileManifestRow)).scalars().all()

        seen_dirs: set[str] = set()
        entries: list[StorageEntry] = []

        for row in rows:
            up = row.user_path
            if not up.startswith(prefix):
                continue
            rel = up[len(prefix):]
            if not rel:
                continue

            slash_idx = rel.find("/")
            if slash_idx == -1:
                entries.append(StorageEntry(
                    name=row.original_name,
                    path=up,
                    is_dir=row.is_dir,
                    size=row.size,
                    modified_at=row.modified_at,
                ))
            else:
                dir_name = rel[:slash_idx]
                dir_path = prefix + dir_name
                if dir_path not in seen_dirs:
                    seen_dirs.add(dir_path)
                    entries.append(StorageEntry(
                        name=dir_name,
                        path=dir_path,
                        is_dir=True,
                        size=0,
                        modified_at=row.modified_at,
                    ))

        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))

    def resolve(self, path: str) -> Path:
        norm = self._normalize(path)
        if norm == "/":
            return self._root
        row = self._row(norm)
        if row is None:
            raise FileNotFoundError(f"Not found in storage: {path!r}")
        if row.is_dir:
            return self._root
        data = self._decrypt((self._root / row.id).read_bytes())
        tmp = tempfile.NamedTemporaryFile(suffix=row.suffix, delete=False)
        try:
            tmp.write(data)
        finally:
            tmp.close()
        self._temp_files.append(tmp.name)
        return Path(tmp.name)

    def read(self, path: str) -> bytes:
        norm = self._normalize(path)
        row = self._row(norm)
        if row is None or row.is_dir:
            raise FileNotFoundError(f"Not found in storage: {path!r}")
        return self._decrypt((self._root / row.id).read_bytes())

    def stat(self, path: str) -> StorageEntry | None:
        norm = self._normalize(path)
        row = self._row(norm)
        if row is None:
            return None
        return StorageEntry(
            name=row.original_name,
            path=norm,
            is_dir=row.is_dir,
            size=row.size,
            modified_at=row.modified_at,
        )

    def write(self, path: str, data: bytes) -> None:
        from verdikt.storage.orm import FileManifestRow

        norm = self._normalize(path)
        row = self._row(norm)
        file_id = row.id if row is not None else str(uuid4())
        encrypted = self._encrypt(data)
        (self._root / file_id).write_bytes(encrypted)

        name = norm.split("/")[-1]
        suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        now = datetime.now(timezone.utc)

        if row is None:
            self._session.add(FileManifestRow(
                id=file_id,
                user_path=norm,
                original_name=name,
                suffix=suffix,
                is_dir=False,
                size=len(data),
                modified_at=now,
            ))
        else:
            row.size = len(data)
            row.modified_at = now

        self._session.commit()

    def mkdir(self, path: str) -> None:
        from verdikt.storage.orm import FileManifestRow

        norm = self._normalize(path)
        if norm == "/" or self._row(norm) is not None:
            return
        name = norm.split("/")[-1]
        self._session.add(FileManifestRow(
            id=str(uuid4()),
            user_path=norm,
            original_name=name,
            suffix="",
            is_dir=True,
            size=0,
            modified_at=datetime.now(timezone.utc),
        ))
        self._session.commit()

    def delete(self, path: str) -> None:
        from sqlalchemy import select
        from verdikt.storage.orm import FileManifestRow

        norm = self._normalize(path)
        if norm == "/":
            raise ValueError("Cannot delete storage root")

        row = self._row(norm)
        if row is not None and not row.is_dir:
            (self._root / row.id).unlink(missing_ok=True)
            self._session.delete(row)
            self._session.commit()
            return

        prefix = norm + "/"
        children = self._session.execute(
            select(FileManifestRow).where(FileManifestRow.user_path.startswith(prefix))
        ).scalars().all()
        for child in children:
            if not child.is_dir:
                (self._root / child.id).unlink(missing_ok=True)
            self._session.delete(child)
        if row is not None:
            self._session.delete(row)
        self._session.commit()

    def exists(self, path: str) -> bool:
        from sqlalchemy import select, func
        from verdikt.storage.orm import FileManifestRow

        norm = self._normalize(path)
        if norm == "/":
            return True
        if self._row(norm) is not None:
            return True
        prefix = norm + "/"
        count = self._session.execute(
            select(func.count()).select_from(FileManifestRow)
            .where(FileManifestRow.user_path.startswith(prefix))
        ).scalar_one()
        return count > 0

    def is_dir(self, path: str) -> bool:
        from sqlalchemy import select, func
        from verdikt.storage.orm import FileManifestRow

        norm = self._normalize(path)
        if norm == "/":
            return True
        row = self._row(norm)
        if row is not None:
            return row.is_dir
        prefix = norm + "/"
        count = self._session.execute(
            select(func.count()).select_from(FileManifestRow)
            .where(FileManifestRow.user_path.startswith(prefix))
        ).scalar_one()
        return count > 0

    def cleanup(self) -> None:
        for tmp in self._temp_files:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
        self._temp_files.clear()

    def migrate_plaintext_files(self) -> int:
        """Encrypt any legacy plaintext files found in the storage root.

        Called once per user on first request after upgrade. Returns the number
        of files migrated.
        """
        migrated = 0
        for old_path in sorted(self._root.rglob("*")):
            if not old_path.is_file():
                continue
            if _looks_like_uuid(old_path.name):
                continue
            try:
                rel = "/" + str(old_path.relative_to(self._root)).replace(os.sep, "/")
                data = old_path.read_bytes()
                self.write(rel, data)
                old_path.unlink()
                parent = old_path.parent
                while parent != self._root and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                log.info("encrypted legacy file: %s", rel)
                migrated += 1
            except Exception as exc:
                log.warning("failed to encrypt legacy file %s: %s", old_path, exc)
        return migrated


def _looks_like_uuid(name: str) -> bool:
    return (
        len(name) == 36
        and name[8] == "-"
        and name[13] == "-"
        and name[18] == "-"
        and name[23] == "-"
    )
