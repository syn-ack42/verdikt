"""Immich plugin — fetch photos from a self-hosted Immich instance.

Supports three source types:
  album   — all assets in a specific album (by album UUID)
  search  — assets matching a metadata search query
  all     — all photos in the library (paginated)

Storage modes (thumbnail_size config key):
  preview   (default) — ~200 KB JPEG at 1280 px; fetched once during pipeline chunk phase
  thumbnail — ~30 KB JPEG at 250 px; fetched once
  none      — content never stored; fetched from Immich on every access

Writeback:
  Writes weighted-average Verdikt ratings as Immich star ratings (1–5).
  Writes LLM-generated chunk descriptions back to the Immich asset description,
  prefixed with "#verdikt:" for idempotent re-writeback.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import httpx

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase

log = logging.getLogger(__name__)

_DEFAULT_MAX_ITEMS = 500
_PAGE_SIZE = 250
_BATCH_SIZE = 50  # items per batched-ingest page


class ImmichPlugin(PluginBase):
    plugin_name = "immich"
    supported_domains: ClassVar[frozenset[Domain]] = frozenset({Domain.IMAGE})

    def __init__(self, config: dict) -> None:
        self._base_url = config.get("base_url", "").rstrip("/")
        self._api_key = config.get("api_key", "")
        self._thumbnail_size = config.get("thumbnail_size", "preview")
        self._sources: list[dict] = config.get("sources") or [{"type": "all", "max_items": _DEFAULT_MAX_ITEMS}]

    # ── PluginBase protocol ────────────────────────────────────────────────────

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "title": "Immich",
            "description": "Fetch photos from a self-hosted Immich instance",
            "type": "object",
            "properties": {
                "base_url": {
                    "type": "string",
                    "format": "uri",
                    "title": "Immich URL",
                    "description": "e.g. http://192.168.1.10:2283",
                },
                "api_key": {
                    "type": "string",
                    "format": "password",
                    "title": "API Key",
                    "description": "Create one in Immich › Account Settings › API Keys",
                },
                "thumbnail_size": {
                    "type": "string",
                    "enum": ["preview", "thumbnail", "none"],
                    "title": "Image storage",
                    "default": "preview",
                    "description": (
                        "preview (~200 KB, default) — store once at ingest; "
                        "thumbnail (~30 KB) — store once, smaller; "
                        "none — never store, fetch from Immich on every access (Immich must always be reachable)"
                    ),
                },
                "sources": {
                    "type": "array",
                    "title": "Sources",
                    "default": [{"type": "all", "max_items": 500}],
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["album", "search", "all"],
                                "title": "Type",
                                "description": "album — one specific album  ·  search — photos matching a query  ·  all — entire library",
                            },
                            "album_id": {
                                "type": "string",
                                "title": "Album ID",
                                "description": "Immich album UUID (for type=album)",
                            },
                            "query": {
                                "type": "string",
                                "title": "Search query",
                                "description": "Metadata search query, e.g. a person or place name (for type=search)",
                            },
                            "max_items": {
                                "type": "integer",
                                "title": "Max items",
                                "default": 500,
                                "minimum": 1,
                                "maximum": 5000,
                            },
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["base_url", "api_key"],
        }

    @classmethod
    def help_markdown(cls) -> str:
        here = Path(__file__).with_name("immich_help.md")
        return here.read_text(encoding="utf-8") if here.exists() else ""

    @classmethod
    def supports_remote_content(cls) -> bool:
        return True

    @classmethod
    def plugin_actions(cls) -> list[dict]:
        return [{
            "name": "writeback",
            "title": "Write back to Immich",
            "description": "Push Verdikt ratings and AI descriptions back to Immich assets.",
            "options_schema": {
                "type": "object",
                "properties": {
                    "write_ratings": {
                        "type": "boolean",
                        "title": "Write ratings as Immich star ratings (1–5)",
                        "default": True,
                    },
                    "write_descriptions": {
                        "type": "boolean",
                        "title": "Write AI-generated descriptions (prefixed #verdikt:)",
                        "default": True,
                    },
                },
            },
        }]

    def run_action(self, action_name: str, project_id: str, session: object, options: dict) -> dict:
        if action_name == "writeback":
            return self.writeback(project_id, session, options)
        raise NotImplementedError(action_name)

    # ── Batched ingest protocol ────────────────────────────────────────────────

    @classmethod
    def supports_batched_ingest(cls) -> bool:
        return True

    def ingest_batch(self, project_id: str, state: dict | None) -> tuple[list[MaterialItem], dict | None]:
        """Fetch one page of Immich assets.

        State shape: {"source_index": int, "page": int}
        Returns (items, next_state). next_state is None when all sources are exhausted.
        """
        if state is None:
            state = {"source_index": 0, "page": 1}

        source_index: int = state.get("source_index", 0)
        page: int = state.get("page", 1)

        while source_index < len(self._sources):
            source = self._sources[source_index]
            src_type = source.get("type", "all")
            max_items = int(source.get("max_items") or _DEFAULT_MAX_ITEMS)

            if src_type == "album":
                # Albums are fetched all at once (no server-side pagination)
                if page > 1:
                    source_index += 1
                    page = 1
                    continue
                assets = self._album_assets(source.get("album_id", ""), max_items)
                items = [i for i in (self._asset_to_item(a, project_id) for a in assets) if i]
                next_si = source_index + 1
                return items, ({"source_index": next_si, "page": 1} if next_si < len(self._sources) else None)

            # search / all — paginated
            max_pages = (max_items + _BATCH_SIZE - 1) // _BATCH_SIZE
            if page > max_pages:
                source_index += 1
                page = 1
                continue

            batch_size = min(_BATCH_SIZE, max_items - (page - 1) * _BATCH_SIZE)
            body: dict = {"type": "IMAGE", "page": page, "size": batch_size}
            if src_type == "search":
                body["query"] = source.get("query", "")

            try:
                data = self._post("/api/search/metadata", body).json()
            except Exception as exc:
                raise RuntimeError(f"Immich fetch failed (source {source_index}, page {page}): {exc}") from exc

            raw = data.get("assets", {}).get("items", [])
            if not raw:
                # Source exhausted before max_items
                source_index += 1
                page = 1
                continue

            items = [i for i in (self._asset_to_item(a, project_id) for a in raw) if i]

            has_next_page = (
                data.get("assets", {}).get("nextPage") is not None
                and len(raw) >= batch_size
                and page < max_pages
            )
            if has_next_page:
                return items, {"source_index": source_index, "page": page + 1}
            next_si = source_index + 1
            return items, ({"source_index": next_si, "page": 1} if next_si < len(self._sources) else None)

        return [], None

    # ── Fetch ──────────────────────────────────────────────────────────────────

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        seen: set[str] = set()
        for source in self._sources:
            src_type = source.get("type", "all")
            max_items = int(source.get("max_items") or _DEFAULT_MAX_ITEMS)
            if src_type == "album":
                assets = self._album_assets(source.get("album_id", ""), max_items)
            elif src_type == "search":
                assets = self._search_assets(source.get("query", ""), max_items)
            else:
                assets = self._all_assets(max_items)

            for asset in assets:
                asset_id = asset.get("id", "")
                if not asset_id or asset_id in seen:
                    continue
                seen.add(asset_id)
                item = self._asset_to_item(asset, project_id)
                if item is not None:
                    yield item

    def fetch_content(self, source_path: str) -> bytes:
        asset_id = source_path.removeprefix("immich://")
        size = self._thumbnail_size if self._thumbnail_size != "none" else "preview"
        resp = self._get(f"/api/assets/{asset_id}/thumbnail?size={size}")
        return resp.content

    def estimate_count(self) -> int | None:
        total = 0
        unknown = False
        for source in self._sources:
            src_type = source.get("type", "all")
            max_items = int(source.get("max_items") or _DEFAULT_MAX_ITEMS)
            if src_type == "album":
                try:
                    album_id = source.get("album_id", "")
                    data = self._get(f"/api/albums/{album_id}?withoutAssets=true").json()
                    total += min(data.get("assetCount", 0), max_items)
                except Exception:
                    unknown = True
            else:
                # search/all: Immich's metadata-search `total` field is unreliable
                # when using size=1 (some versions return total=1). Cap at max_items
                # and signal unknown so the UI shows N/? rather than N/1.
                total += max_items
                unknown = True
        if unknown:
            return None
        return total or None

    def get_updated_ats(self, work_ids: list[str]) -> dict:
        from datetime import datetime, timezone
        result: dict = {}
        for source_path in work_ids:
            asset_id = source_path.removeprefix("immich://")
            try:
                data = self._get(f"/api/assets/{asset_id}").json()
                updated_str = data.get("updatedAt") or data.get("fileModifiedAt")
                if updated_str:
                    result[source_path] = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except Exception:
                result[source_path] = None
        return result

    def get_new_work_ids(self, existing: set[str]) -> list[str]:
        new_ids: list[str] = []
        seen: set[str] = set()
        for source in self._sources:
            src_type = source.get("type", "all")
            max_items = int(source.get("max_items") or _DEFAULT_MAX_ITEMS)
            if src_type == "album":
                assets = self._album_assets(source.get("album_id", ""), max_items)
            elif src_type == "search":
                assets = self._search_assets(source.get("query", ""), max_items)
            else:
                assets = self._all_assets(max_items)
            for asset in assets:
                asset_id = asset.get("id", "")
                source_path = f"immich://{asset_id}"
                if source_path not in existing and source_path not in seen:
                    new_ids.append(source_path)
                    seen.add(source_path)
        return new_ids

    def fetch_by_ids(self, project_id: str, work_ids: list[str], **_kwargs) -> Iterator[MaterialItem]:
        for source_path in work_ids:
            asset_id = source_path.removeprefix("immich://")
            try:
                asset = self._get(f"/api/assets/{asset_id}").json()
                item = self._asset_to_item(asset, project_id)
                if item is not None:
                    yield item
            except Exception:
                log.exception("immich: failed to fetch asset %s", asset_id)

    # ── Writeback ──────────────────────────────────────────────────────────────

    def writeback(self, project_id: str, session: object, options: dict) -> dict:
        from sqlalchemy.orm import Session as _Session

        write_ratings = options.get("write_ratings", False)
        write_descriptions = options.get("write_descriptions", False)

        if not write_ratings and not write_descriptions:
            return {"updated": 0, "skipped": 0, "errors": []}

        from verdikt.storage.sqlite import (
            SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore, SQLiteRatingStore,
        )

        sess: _Session = session  # type: ignore[assignment]
        proj = SQLiteProjectStore(sess).get(project_id)
        mat_store = SQLiteMaterialStore(sess)
        chunk_store = SQLiteChunkStore(sess)
        rating_store = SQLiteRatingStore(sess)

        items = mat_store.list_by_source_plugin(project_id, self.plugin_name)
        dim_weights = {d.name: d.weight for d in proj.rating_dimensions} if proj else {}

        updated = skipped = 0
        errors: list[str] = []

        for item in items:
            asset_id = (item.source_path or "").removeprefix("immich://")
            if not asset_id:
                skipped += 1
                continue

            chunks = chunk_store.list_by_material(item.id)
            if not chunks:
                skipped += 1
                continue
            chunk = chunks[0]

            payload: dict = {}

            if write_ratings:
                ratings = [r for r in rating_store.list_by_chunk(chunk.id) if not r.skipped]
                if ratings:
                    per_rating_scores: list[float] = []
                    for r in ratings:
                        dim_score_values = list(r.dimension_scores.values())
                        if not dim_score_values:
                            continue
                        w_sum = sum(dim_weights.get(d, 1.0) for d in r.dimension_scores)
                        if w_sum == 0:
                            per_rating_scores.append(sum(dim_score_values) / len(dim_score_values))
                        else:
                            per_rating_scores.append(
                                sum(v * dim_weights.get(d, 1.0) for d, v in r.dimension_scores.items()) / w_sum
                            )
                    if per_rating_scores:
                        star = max(1, min(5, round(sum(per_rating_scores) / len(per_rating_scores))))
                        payload["rating"] = star

            if write_descriptions and chunk.description:
                try:
                    current = self._get(f"/api/assets/{asset_id}").json()
                    existing_desc = current.get("exifInfo", {}).get("description") or ""
                except Exception:
                    existing_desc = ""

                new_desc = _merge_description(existing_desc, chunk.description)
                payload["description"] = new_desc

            if not payload:
                skipped += 1
                continue

            try:
                self._put(f"/api/assets/{asset_id}", payload)
                updated += 1
            except Exception as exc:
                errors.append(f"{asset_id}: {exc}")
                skipped += 1

        return {"updated": updated, "skipped": skipped, "errors": errors}

    # ── Immich API helpers ─────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"x-api-key": self._api_key, "Accept": "application/json"}

    def _get(self, path: str) -> httpx.Response:
        resp = httpx.get(f"{self._base_url}{path}", headers=self._headers(), timeout=30.0)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, body: dict) -> httpx.Response:
        resp = httpx.post(
            f"{self._base_url}{path}",
            headers={**self._headers(), "Content-Type": "application/json"},
            content=json.dumps(body),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp

    def _put(self, path: str, body: dict) -> httpx.Response:
        resp = httpx.put(
            f"{self._base_url}{path}",
            headers={**self._headers(), "Content-Type": "application/json"},
            content=json.dumps(body),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp

    # ── Asset enumeration ──────────────────────────────────────────────────────

    def _album_assets(self, album_id: str, max_items: int) -> list[dict]:
        if not album_id:
            return []
        try:
            data = self._get(f"/api/albums/{album_id}").json()
            return data.get("assets", [])[:max_items]
        except Exception:
            log.exception("immich: failed to fetch album %s", album_id)
            return []

    def _search_assets(self, query: str, max_items: int) -> list[dict]:
        return self._paginate_search({"type": "IMAGE", "query": query}, max_items)

    def _all_assets(self, max_items: int) -> list[dict]:
        return self._paginate_search({"type": "IMAGE"}, max_items)

    def _paginate_search(self, body_base: dict, max_items: int) -> list[dict]:
        assets: list[dict] = []
        page = 1
        while len(assets) < max_items:
            try:
                data = self._post("/api/search/metadata", {
                    **body_base,
                    "page": page,
                    "size": min(_PAGE_SIZE, max_items - len(assets)),
                }).json()
            except Exception:
                log.exception("immich: search page %d failed", page)
                break
            items = data.get("assets", {}).get("items", [])
            if not items:
                break
            assets.extend(items)
            # Use nextPage (null when no more pages) as primary stop signal.
            # Fall back to "got fewer items than requested" for older Immich versions
            # that don't return nextPage. Do NOT rely on `total` — it defaults to 0
            # when the field is missing, which would break pagination after page 1.
            next_page = data.get("assets", {}).get("nextPage")
            if next_page is None or len(items) < _PAGE_SIZE:
                break
            page += 1
        return assets[:max_items]

    # ── Asset → MaterialItem ───────────────────────────────────────────────────

    def _asset_to_item(self, asset: dict, project_id: str) -> MaterialItem | None:
        asset_id = asset.get("id", "")
        if not asset_id:
            return None

        original_name = asset.get("originalFileName", asset_id)
        work_title = Path(original_name).stem

        thumbnail_size = self._thumbnail_size
        if thumbnail_size != "none":
            try:
                content = self._get(f"/api/assets/{asset_id}/thumbnail?size={thumbnail_size}").content
                content_is_remote = False
            except Exception:
                log.exception("immich: failed to fetch thumbnail for asset %s", asset_id)
                content = b""
                content_is_remote = True
        else:
            content = b""
            content_is_remote = True

        return MaterialItem(
            project_id=project_id,
            source_plugin=self.plugin_name,
            source_path=f"immich://{asset_id}",
            url=f"{self._base_url}/photos/{asset_id}",
            work_title=work_title,
            content=content,
            content_is_remote=content_is_remote,
            content_hash=asset.get("checksum") or asset_id,
            domain=Domain.IMAGE,
            content_type=ContentType.JPEG,
            plugin_metadata={
                "asset_id": asset_id,
                "base_url": self._base_url,
                "original_filename": original_name,
                "file_created_at": asset.get("fileCreatedAt", ""),
            },
        )


def _merge_description(existing: str, verdikt_desc: str) -> str:
    """Merge a Verdikt description into an existing Immich description.

    - Replaces any existing '#verdikt:' line (idempotent)
    - Appends '#verdikt: ...' if no such line exists
    """
    verdikt_line = f"#verdikt: {verdikt_desc}"
    if not existing:
        return verdikt_line
    lines = existing.splitlines()
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("#verdikt:"):
            new_lines.append(verdikt_line)
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(verdikt_line)
    return "\n".join(new_lines)
