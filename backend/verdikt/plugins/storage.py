"""Storage plugin — ingests files from verdikt's managed storage area.

Config shape:
    selections: [{path: str, mode: "folder"|"file"}]
        folder = whole directory; new files discovered on both ingest and update
        file   = specific file only; never auto-expands

Runtime-only keys injected by the router (not stored in DB):
    _storage_root    — absolute path to the files directory (for source_path construction)
    _storage_backend — EncryptedStorageBackend instance; when present, all file access
                       goes through it rather than the real filesystem
    _domain          — project domain ("text" | "image"); controls which file types are accepted
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase
from verdikt.plugins.filedrop import FileDropPlugin as _Extractor, _EXT_TO_CONTENT_TYPE

log = logging.getLogger(__name__)

_IMAGE_EXT_TO_CONTENT_TYPE: dict[str, ContentType] = {
    ".jpg": ContentType.JPEG,
    ".jpeg": ContentType.JPEG,
    ".png": ContentType.PNG,
    ".webp": ContentType.JPEG,   # closest available; webp is treated as image/jpeg for now
    ".gif": ContentType.PNG,
    ".bmp": ContentType.PNG,
    ".tiff": ContentType.PNG,
    ".tif": ContentType.PNG,
}


class StoragePlugin(PluginBase):
    plugin_name = "storage"
    supported_domains = frozenset({Domain.TEXT, Domain.IMAGE})

    def __init__(self, config: dict) -> None:
        self._config = config
        root = config.get("_storage_root", "")
        self._storage_root = Path(root) if root else Path()
        self._backend = config.get("_storage_backend")  # EncryptedStorageBackend | None
        domain_str = config.get("_domain", "text")
        self._domain = Domain(domain_str) if domain_str in Domain._value2member_map_ else Domain.TEXT
        if self._domain == Domain.IMAGE:
            self.SUPPORTED_EXTENSIONS = set(_IMAGE_EXT_TO_CONTENT_TYPE)
        else:
            self.SUPPORTED_EXTENSIONS = set(_EXT_TO_CONTENT_TYPE)

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "title": "File Drop",
            "description": "Ingest files from verdikt storage",
            "properties": {
                "selections": {
                    "type": "array",
                    "title": "Selected files and folders",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "mode": {"type": "string", "enum": ["folder", "file"]},
                        },
                        "required": ["path", "mode"],
                    },
                    "default": [],
                },
            },
        }

    @classmethod
    def help_markdown(cls) -> str:
        from pathlib import Path as _Path
        return (_Path(__file__).parent / "storage_help.md").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Path helpers (filesystem mode)
    # ------------------------------------------------------------------

    def _abs(self, storage_path: str) -> Path:
        return self._storage_root / storage_path.lstrip("/")

    def _rel(self, abs_path: Path) -> str:
        return "/" + str(abs_path.relative_to(self._storage_root)).replace("\\", "/")

    # ------------------------------------------------------------------
    # File iteration
    # ------------------------------------------------------------------

    def _files_for_selection(self, sel: dict) -> Iterator[tuple[Path, str | None]]:
        """Yield (resolved_path, virtual_path_or_None) tuples.

        virtual_path is set in backend mode so that source_path can be
        constructed as a stable identifier independent of the temp file path.
        In filesystem mode virtual_path is None and resolved_path IS the stable path.
        """
        path, mode = sel["path"], sel["mode"]
        if self._backend is not None:
            yield from self._backend_files_for_selection(path, mode)
        else:
            fs = self._abs(path)
            if mode == "folder":
                if fs.is_dir():
                    for p in sorted(
                        p for p in fs.rglob("*")
                        if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTENSIONS
                    ):
                        yield (p, None)
            elif mode == "file":
                if fs.is_file() and fs.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    yield (fs, None)

    def _backend_files_for_selection(self, path: str, mode: str) -> Iterator[tuple[Path, str]]:
        if mode == "file":
            entry = self._backend.stat(path)
            if entry and not entry.is_dir and Path(entry.name).suffix.lower() in self.SUPPORTED_EXTENSIONS:
                yield (self._backend.resolve(path), path)
        elif mode == "folder":
            yield from self._backend_list_recursive(path)

    def _backend_list_recursive(self, path: str) -> Iterator[tuple[Path, str]]:
        for entry in self._backend.list(path):
            if entry.is_dir:
                yield from self._backend_list_recursive(entry.path)
            elif Path(entry.name).suffix.lower() in self.SUPPORTED_EXTENSIONS:
                yield (self._backend.resolve(entry.path), entry.path)

    def _backend_virtual_paths(self, path: str) -> Iterator[str]:
        """Yield virtual paths for supported files under path (no filesystem access)."""
        for entry in self._backend.list(path):
            if entry.is_dir:
                yield from self._backend_virtual_paths(entry.path)
            elif Path(entry.name).suffix.lower() in self.SUPPORTED_EXTENSIONS:
                yield entry.path

    # ------------------------------------------------------------------
    # MaterialItem construction
    # ------------------------------------------------------------------

    def _make_item(self, file_path: Path, project_id: str, virtual_path: str | None = None) -> MaterialItem | None:
        ext = file_path.suffix.lower()

        if virtual_path is not None:
            source_path = str((self._storage_root / virtual_path.lstrip("/")).resolve()) \
                if self._storage_root != Path() else virtual_path
            work_title = Path(virtual_path).stem
            work_id = virtual_path
        else:
            source_path = str(file_path.resolve())
            work_title = file_path.stem
            work_id = self._rel(file_path)

        if self._domain == Domain.IMAGE:
            try:
                raw = file_path.read_bytes()
            except Exception as exc:
                log.warning("storage: skipping %s file — %s", ext, exc)
                return None
            content_type = _IMAGE_EXT_TO_CONTENT_TYPE.get(ext, ContentType.JPEG)
            return MaterialItem(
                project_id=project_id,
                source_plugin=self.plugin_name,
                source_path=source_path,
                content_hash=hashlib.sha256(raw).hexdigest(),
                url=file_path.as_uri(),
                work_title=work_title,
                content=raw,
                domain=Domain.IMAGE,
                content_type=content_type,
                plugin_metadata={"work_id": work_id},
            )

        # Text domain
        extractor = _Extractor({"path": str(file_path.parent)})
        try:
            text = extractor._extract_text(file_path)
        except Exception as exc:
            log.warning("storage: skipping %s file — %s", ext, exc)
            return None
        if not text or not text.strip():
            return None
        raw_bytes = text.encode("utf-8") if isinstance(text, str) else text
        return MaterialItem(
            project_id=project_id,
            source_plugin=self.plugin_name,
            source_path=source_path,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            url=file_path.as_uri(),
            work_title=work_title,
            content=text,
            domain=Domain.TEXT,
            content_type=_EXT_TO_CONTENT_TYPE.get(ext, ContentType.PLAIN),
            plugin_metadata={"work_id": work_id},
        )

    # ------------------------------------------------------------------
    # PluginBase interface
    # ------------------------------------------------------------------

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        seen: set[str] = set()
        for sel in self._config.get("selections", []):
            for fp, virtual_path in self._files_for_selection(sel):
                key = virtual_path if virtual_path is not None else str(fp.resolve())
                if key in seen:
                    continue
                seen.add(key)
                item = self._make_item(fp, project_id, virtual_path=virtual_path)
                if item is not None:
                    yield item

    def get_updated_ats(self, work_ids: list[str]) -> dict[str, datetime | None]:
        if self._backend is not None:
            result: dict[str, datetime | None] = {}
            for wid in work_ids:
                entry = self._backend.stat(wid)
                result[wid] = entry.modified_at if entry else None
            return result

        result = {}
        for wid in work_ids:
            fp = self._abs(wid)
            if fp.is_file():
                result[wid] = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
            else:
                result[wid] = None
        return result

    def fetch_by_ids(self, project_id: str, work_ids: list[str], **kwargs) -> Iterator[MaterialItem]:
        if self._backend is not None:
            for wid in work_ids:
                try:
                    temp_path = self._backend.resolve(wid)
                    item = self._make_item(temp_path, project_id, virtual_path=wid)
                    if item is not None:
                        yield item
                except FileNotFoundError:
                    pass
            return

        for wid in work_ids:
            fp = self._abs(wid)
            if not fp.is_file():
                continue
            item = self._make_item(fp, project_id)
            if item is not None:
                yield item

    def estimate_count(self) -> int | None:
        if self._backend is not None:
            count = 0
            for sel in self._config.get("selections", []):
                count += sum(1 for _ in self._backend_virtual_paths(sel["path"]))
            return count

        seen: set[str] = set()
        for sel in self._config.get("selections", []):
            for fp, _ in self._files_for_selection(sel):
                seen.add(str(fp.resolve()))
        return len(seen)

    def get_new_work_ids(self, existing: set[str]) -> list[str]:
        new: list[str] = []
        seen: set[str] = set()

        if self._backend is not None:
            for sel in self._config.get("selections", []):
                if sel.get("mode") != "folder":
                    continue
                for vpath in self._backend_virtual_paths(sel["path"]):
                    if vpath not in existing and vpath not in seen:
                        seen.add(vpath)
                        new.append(vpath)
            return new

        for sel in self._config.get("selections", []):
            if sel.get("mode") != "folder":
                continue
            for fp, _ in self._files_for_selection(sel):
                rel = self._rel(fp)
                if rel not in existing and rel not in seen:
                    seen.add(rel)
                    new.append(rel)
        return new
