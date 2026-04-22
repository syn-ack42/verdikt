"""Storage plugin — ingests files from verdikt's managed storage area.

Config shape:
    selections: [{path: str, mode: "folder"|"file"}]
        folder = whole directory; new files discovered on both ingest and update
        file   = specific file only; never auto-expands

The storage root is injected at runtime via _storage_root in the config dict.
It is never stored in the DB — the router adds it before instantiation.
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


class StoragePlugin(PluginBase):
    plugin_name = "storage"
    SUPPORTED_EXTENSIONS = set(_EXT_TO_CONTENT_TYPE)

    def __init__(self, config: dict) -> None:
        self._config = config
        root = config.get("_storage_root", "")
        self._storage_root = Path(root) if root else Path()

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

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _abs(self, storage_path: str) -> Path:
        return self._storage_root / storage_path.lstrip("/")

    def _rel(self, abs_path: Path) -> str:
        return "/" + str(abs_path.relative_to(self._storage_root)).replace("\\", "/")

    # ------------------------------------------------------------------
    # File iteration
    # ------------------------------------------------------------------

    def _files_for_selection(self, sel: dict) -> Iterator[Path]:
        path, mode = sel["path"], sel["mode"]
        fs = self._abs(path)
        if mode == "folder":
            if fs.is_dir():
                yield from sorted(
                    p for p in fs.rglob("*")
                    if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTENSIONS
                )
        elif mode == "file":
            if fs.is_file() and fs.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                yield fs

    def _make_item(self, file_path: Path, project_id: str) -> MaterialItem | None:
        ext = file_path.suffix.lower()
        extractor = _Extractor({"path": str(file_path.parent)})
        try:
            text = extractor._extract_text(file_path)
        except Exception as exc:
            log.warning("storage: skipping %s — %s", file_path.name, exc)
            return None
        if not text or not text.strip():
            return None
        raw = text.encode("utf-8") if isinstance(text, str) else text
        return MaterialItem(
            project_id=project_id,
            source_plugin=self.plugin_name,
            source_path=str(file_path.resolve()),
            content_hash=hashlib.sha256(raw).hexdigest(),
            url=file_path.as_uri(),
            work_title=file_path.stem,
            content=text,
            domain=Domain.TEXT,
            content_type=_EXT_TO_CONTENT_TYPE[ext],
            plugin_metadata={"work_id": self._rel(file_path)},
        )

    # ------------------------------------------------------------------
    # PluginBase interface
    # ------------------------------------------------------------------

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        seen: set[str] = set()
        for sel in self._config.get("selections", []):
            for fp in self._files_for_selection(sel):
                key = str(fp.resolve())
                if key in seen:
                    continue
                seen.add(key)
                item = self._make_item(fp, project_id)
                if item is not None:
                    yield item

    def get_updated_ats(self, work_ids: list[str]) -> dict[str, datetime | None]:
        result: dict[str, datetime | None] = {}
        for wid in work_ids:
            fp = self._abs(wid)
            if fp.is_file():
                result[wid] = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
            else:
                result[wid] = None
        return result

    def fetch_by_ids(self, project_id: str, work_ids: list[str], **kwargs) -> Iterator[MaterialItem]:
        for wid in work_ids:
            fp = self._abs(wid)
            if not fp.is_file():
                continue
            item = self._make_item(fp, project_id)
            if item is not None:
                yield item

    def estimate_count(self) -> int | None:
        seen: set[str] = set()
        for sel in self._config.get("selections", []):
            for fp in self._files_for_selection(sel):
                seen.add(str(fp.resolve()))
        return len(seen)

    def get_new_work_ids(self, existing: set[str]) -> list[str]:
        """Return storage-relative paths for files in folder-mode selections not yet in existing."""
        new: list[str] = []
        seen: set[str] = set()
        for sel in self._config.get("selections", []):
            if sel.get("mode") != "folder":
                continue
            for fp in self._files_for_selection(sel):
                rel = self._rel(fp)
                if rel not in existing and rel not in seen:
                    seen.add(rel)
                    new.append(rel)
        return new
