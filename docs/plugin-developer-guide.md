# Verdikt Plugin Developer Guide

This guide explains how to write a Verdikt content source plugin. A plugin fetches raw material from an external source (a website, an API, a local file format) and normalises it into `MaterialItem` objects. The rest of the system — chunking, embedding, clustering, rating, and recommendation — happens automatically.

**Plugins know nothing about preference learning. They fetch, parse, and emit.**

## Concepts

### What a plugin does

1. Receives a user-supplied config dict (validated against a JSON Schema you declare).
2. Connects to a content source and retrieves items.
3. Yields each item as a `MaterialItem` — the universal data contract.

The Verdikt pipeline picks up every `MaterialItem` your plugin yields and processes it from there.

### Identity and upserts

Verdikt uses `source_plugin` + `source_path` as the identity key for upserts. If you ingest the same item twice, Verdikt detects it via `content_hash` and skips or updates it rather than duplicating. **Always set `source_path` to a stable, unique identifier for each item** (URL, file path, or a canonical ID string). Always compute `content_hash` as the SHA-256 hex of the raw content bytes.

---

## Quickstart

### 1. Create a package

```
my_verdikt_plugin/
    __init__.py
    plugin.py
pyproject.toml
```

### 2. Implement `PluginBase`

```python
# my_verdikt_plugin/plugin.py
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import ClassVar

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase


class MyPlugin(PluginBase):
    plugin_name = "myplugin"   # must be unique across installed plugins

    # Optional: restrict which project domains this plugin appears in.
    # Default is frozenset(Domain) — all domains. Restrict when your source
    # only makes sense for a specific domain (e.g. a text-only API).
    supported_domains: ClassVar[frozenset[Domain]] = frozenset({Domain.TEXT})

    def __init__(self, config: dict) -> None:
        self._config = config
        self._api_key = config["api_key"]
        self._query = config.get("query", "")

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "format": "password",
                },
                "query": {
                    "type": "string",
                    "title": "Search query",
                    "description": "Keywords to search for",
                },
                "max_items": {
                    "type": "integer",
                    "title": "Max items",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "required": ["api_key"],
        }

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        for raw in self._call_api():
            content = raw["body"]
            raw_bytes = content.encode("utf-8")
            yield MaterialItem(
                project_id=project_id,
                source_plugin=self.plugin_name,
                source_path=raw["url"],           # stable identity key
                url=raw["url"],
                work_title=raw["title"],
                author=raw.get("author"),
                content=content,
                content_hash=hashlib.sha256(raw_bytes).hexdigest(),
                domain=Domain.TEXT,
                content_type=ContentType.PLAIN,
                plugin_metadata={
                    "item_id": raw["id"],
                    "published_at": raw.get("published_at"),
                },
            )

    def _call_api(self):
        # your HTTP logic here
        ...
```

### 3. Register via `pyproject.toml`

```toml
[project.entry-points."verdikt.plugins"]
myplugin = "my_verdikt_plugin.plugin:MyPlugin"
```

The entry-point name (`myplugin`) must match `plugin_name` on your class.

### 4. Install

```bash
pip install -e .          # development
pip install .             # production
```

Verdikt discovers the plugin automatically via `importlib.metadata.entry_points`. No changes to Verdikt's source code are needed.

---

## The `MaterialItem` contract

`MaterialItem` is the stable public API between your plugin and the rest of Verdikt. It is a Pydantic model. **Your plugin fills provenance and content. The pipeline fills everything else.**

### Fields your plugin must set

| Field | Type | Description |
|---|---|---|
| `project_id` | `str` | Pass through the `project_id` argument from `fetch()`. |
| `source_plugin` | `str` | Your `plugin_name` value. |
| `content` | `str \| bytes` | The full raw content. Prefer `str` for text, `bytes` for binary. |
| `domain` | `Domain` | `Domain.TEXT`, `Domain.IMAGE`, or `Domain.AUDIO`. |
| `content_type` | `ContentType` | MIME type — see table below. |

### Fields your plugin should set

| Field | Type | Description |
|---|---|---|
| `source_path` | `str` | Unique, stable identity key (URL or file path). Used to detect re-ingests. **Set this.** |
| `content_hash` | `str` | `hashlib.sha256(content_bytes).hexdigest()`. Required for change detection. |
| `url` | `str` | Canonical URL for linking back to the source. May equal `source_path`. |
| `work_title` | `str` | Human-readable title shown in the UI. |
| `author` | `str` | Author name, if available. |
| `sequence_position` | `int` | Chapter/track number within a larger work (e.g. chapter 3 of a serial). |
| `plugin_metadata` | `dict` | Arbitrary JSON — store any source-specific fields you need for updates or display. |

### Fields managed by the pipeline (do not set)

`id`, `project_seq`, `pipeline_phase`, `ingested_at` — leave these as defaults.

### `Domain` values

| Value | Use for |
|---|---|
| `Domain.TEXT` | prose, articles, fan fiction, documents |
| `Domain.IMAGE` | photos, artwork, illustrations |
| `Domain.AUDIO` | music, podcasts, recorded speech *(not yet supported — do not use)* |

### `ContentType` values

| Value | Use for |
|---|---|
| `ContentType.PLAIN` | plain text |
| `ContentType.HTML` | HTML content |
| `ContentType.MARKDOWN` | Markdown |
| `ContentType.EPUB` | EPUB e-books |
| `ContentType.PDF` | PDF documents |
| `ContentType.RTF` | RTF documents |
| `ContentType.JPEG` / `ContentType.PNG` | images |
| `ContentType.MP3` | audio |

---

## Optional methods

Override these to improve performance or user experience. Verdikt calls them if you provide them; otherwise it falls back to the default behaviour.

### `estimate_count() -> int | None`

Return an approximate item count before fetching starts. Displayed as a progress total in the UI. Overestimates are fine.

```python
def estimate_count(self) -> int | None:
    return self._config.get("max_items", 20)
```

### `get_updated_ats(work_ids: list[str]) -> dict[str, datetime | None]`

Return `{work_id: last_modified_datetime}` for the given work IDs without downloading full content. Verdikt calls this during **Update** to skip works that haven't changed, avoiding unnecessary re-downloads.

`work_id` values are whatever you stored under `plugin_metadata["work_id"]`. If a work_id is absent from the returned dict, Verdikt assumes it needs updating.

```python
def get_updated_ats(self, work_ids: list[str]) -> dict[str, datetime | None]:
    results = {}
    for wid in work_ids:
        results[wid] = self._fetch_last_modified(wid)  # lightweight head request
    return results
```

### `get_new_work_ids(existing: set[str]) -> list[str]`

Called during Update to discover items that should be ingested but aren't yet in `existing`. Useful for plugins that track a feed or folder that grows over time.

```python
def get_new_work_ids(self, existing: set[str]) -> list[str]:
    all_ids = set(self._list_available_ids())
    return list(all_ids - existing)
```

### `fetch_by_ids(project_id, work_ids, **kwargs) -> Iterator[MaterialItem]`

Fetch only the items with the given work IDs. The default implementation calls `fetch()` and filters, which is wasteful if your source supports fetching by ID directly.

```python
def fetch_by_ids(self, project_id, work_ids, **kwargs):
    for wid in work_ids:
        yield self._fetch_single(project_id, wid)
```

---

## Remote content protocol

For plugins that source remote content (e.g. a photo service), it is often preferable to store only a reference at ingest time and fetch the actual bytes lazily rather than downloading everything upfront.

### Opting in

Override two classmethods and one instance method:

```python
@classmethod
def supports_remote_content(cls) -> bool:
    return True

def fetch_content(self, source_path: str) -> bytes:
    """Fetch and return the raw bytes for the item identified by source_path."""
    asset_id = source_path.removeprefix("myservice://")
    return self._http_get_bytes(f"/assets/{asset_id}/file")
```

### How it works

When `supports_remote_content()` returns `True`:

- Set `content=b""` and `content_is_remote=True` on every `MaterialItem` in `fetch()`. Do **not** download bytes at ingest time.
- The pipeline's chunk phase will call `fetch_content(source_path)` for each item to obtain the bytes before chunking.
- A `thumbnail_size` config field (enum: `"preview"` / `"thumbnail"` / `"none"`) controls whether fetched bytes are persisted to `ChunkRow.content` after the first fetch:
  - `"preview"` / `"thumbnail"` — bytes are stored once; all downstream reads (rating display, AI judge) use the DB copy.
  - `"none"` — `ChunkRow.content` stays empty; every access (rating display, AI judge) calls `fetch_content()` on demand. Requires the remote service to be reachable at all times.

```python
# In fetch():
yield MaterialItem(
    project_id=project_id,
    source_plugin=self.plugin_name,
    source_path=f"myservice://{asset_id}",
    content=b"",
    content_is_remote=True,
    content_hash=asset["checksum"],   # hash of the remote original
    domain=Domain.IMAGE,
    content_type=ContentType.JPEG,
    plugin_metadata={"asset_id": asset_id},
)
```

---

## Writeback protocol

Plugins that can push data back to their source (e.g. writing star ratings or descriptions back to a photo service) can implement writeback:

### Opting in

```python
@classmethod
def supports_writeback(cls) -> bool:
    return True

def writeback(self, project_id: str, session, options: dict) -> dict:
    """
    Push data back to the source.

    options keys:
        write_ratings: bool      — push Verdikt star ratings
        write_descriptions: bool — push AI-generated chunk descriptions

    Returns {"updated": N, "skipped": N, "errors": [...]}
    """
    updated, skipped, errors = 0, 0, []
    for item in self._load_items(project_id, session):
        payload = {}
        if options.get("write_ratings"):
            star = self._compute_star_rating(item, session)
            if star is not None:
                payload["rating"] = star
        if options.get("write_descriptions"):
            desc = self._get_description(item, session)
            if desc:
                payload["description"] = desc
        if payload:
            try:
                self._push(item, payload)
                updated += 1
            except Exception as e:
                errors.append(str(e))
        else:
            skipped += 1
    return {"updated": updated, "skipped": skipped, "errors": errors}
```

When `supports_writeback()` returns `True`, Verdikt exposes a **Write back** button on the project dashboard for any project that has the plugin configured. The button opens a modal with opt-in checkboxes for each write type and calls `POST /api/projects/{id}/works/plugins/{name}/writeback`.

---

## Config schema reference

The `config_schema()` classmethod returns a [JSON Schema](https://json-schema.org/) `object`. Verdikt renders the config form automatically from this schema.

### Supported field types

| JSON Schema | Rendered as |
|---|---|
| `{"type": "string"}` | Text input |
| `{"type": "string", "format": "password"}` | Password input (masked) |
| `{"type": "string", "format": "uri"}` | URL input |
| `{"type": "string", "enum": ["a", "b", "c"]}` | Dropdown (`<select>`) |
| `{"type": "integer"}` or `{"type": "number"}` | Number input (respects `minimum`/`maximum`) |
| `{"type": "array", "items": {"type": "string"}}` | Dynamic list of text inputs |
| `{"type": "array", "items": {"type": "string", "format": "uri"}}` | Dynamic list of URL inputs |
| `{"type": "array", "items": {"type": "object", "properties": {...}}}` | Dynamic list of inline rows — each row renders one input per property (URL properties stretch, enum properties render as dropdowns, number properties are compact). When adding a new row, non-URL fields default to the previous row's values. |

Each property inside `items.properties` supports the same field-level keys as top-level properties: `type`, `format`, `enum`, `title`, `minimum`, `maximum`, `default`.

### Conditional fields in object-array rows

Within an object-array, you can hide fields unless a discriminator field matches a specific value. Append `(for type=<value>)` to a field's `"description"` and the UI will show that field only when the row's `type` field equals `<value>`.

```python
"sources": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "type":     {"type": "string", "enum": ["album", "search", "all"], "title": "Source type"},
            "album_id": {"type": "string", "title": "Album ID",
                         "description": "Immich album UUID (for type=album)"},
            "query":    {"type": "string", "title": "Search query",
                         "description": "Metadata search query (for type=search)"},
            "max_items":{"type": "integer", "title": "Max items", "default": 500},
        },
        "required": ["type"],
    },
}
```

In this example, `album_id` is only shown when the row's `type` dropdown is set to `album`, and `query` is only shown when `type` is `search`. The `(for type=X)` clause is stripped from the displayed hint text.

**Example** — a list of search targets each with their own result cap (as used by the built-in AO3 plugin):

```python
"search_urls": {
    "type": "array",
    "title": "Search URLs",
    "description": "One AO3 search URL per row; max_works applies to that row only.",
    "items": {
        "type": "object",
        "properties": {
            "url":       {"type": "string", "format": "uri", "title": "Search URL"},
            "max_works": {"type": "integer", "title": "Max works", "default": 20, "minimum": 1, "maximum": 500},
        },
    },
}
```

Mark required fields with the top-level `"required"` array. Required fields that are empty will be highlighted in the UI on submit.

Provide `"title"` and `"description"` on each property — they appear as the field label and hint text.

---

## Rate limits and terms of service

**You are responsible for your plugin's behaviour.** Verdikt is local-first, but that does not make it invisible.

- Respect the source's `robots.txt` and `Terms of Service`.
- Add configurable delays between requests (`time.sleep(delay)`) and expose the delay as a config field with a sensible minimum.
- Use a descriptive `User-Agent` header that identifies your plugin and provides a contact point: `"MyPlugin/1.0 (verdikt integration; contact@example.com)"`.
- Do not write plugins that make it easy to mass-download content in ways the source prohibits.

---

## Testing your plugin

Use `pytest` with mocked HTTP responses. The `responses` or `httpretty` library works well for HTTP-based plugins.

```python
import responses as resp_lib
import pytest
from my_verdikt_plugin.plugin import MyPlugin

CANNED_RESPONSE = {"id": "1", "url": "https://example.com/1", "title": "A Story", "body": "Once upon a time..."}

@pytest.fixture
def plugin():
    return MyPlugin({"api_key": "test-key", "max_items": 5})

@resp_lib.activate
def test_fetch_yields_material_items(plugin):
    resp_lib.add(resp_lib.GET, "https://api.example.com/search", json=[CANNED_RESPONSE])
    items = list(plugin.fetch("proj-123"))
    assert len(items) == 1
    assert items[0].work_title == "A Story"
    assert items[0].source_plugin == "myplugin"
    assert items[0].content_hash is not None

def test_config_schema_has_required_field(plugin):
    schema = MyPlugin.config_schema()
    assert "api_key" in schema["required"]

def test_estimate_count(plugin):
    assert plugin.estimate_count() == 5
```

### What to test

- `fetch()` yields `MaterialItem` objects with the correct `source_plugin`, `source_path`, `content_hash`, and `domain`
- `config_schema()` shape — `required` fields present, field types correct
- `get_updated_ats()` returns a dict keyed by work ID (if you implement it)
- Auth failure raises a clear exception rather than silently yielding zero items
- Rate limiting / retry logic (if applicable)

---

## Writing an image plugin

Image plugins work identically to text plugins at the `MaterialItem` level. The key differences:

- Set `domain=Domain.IMAGE` and `content_type=ContentType.JPEG` (or `PNG`)
- `content` must be raw image **bytes**, not a string
- Set `supported_domains = frozenset({Domain.IMAGE})` so the plugin only appears in image projects
- The pipeline uses `IdentityChunker` for image projects — each `MaterialItem` becomes exactly one chunk; do not pre-split images yourself
- The pipeline uses `CLIPEmbedder` for image projects — no Ollama embedding is needed
- Compute `content_hash` as `hashlib.sha256(image_bytes).hexdigest()`

```python
class MyImagePlugin(PluginBase):
    plugin_name = "myimages"
    supported_domains: ClassVar[frozenset[Domain]] = frozenset({Domain.IMAGE})

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        for path in self._list_images():
            raw = path.read_bytes()
            yield MaterialItem(
                project_id=project_id,
                source_plugin=self.plugin_name,
                source_path=str(path),
                work_title=path.name,
                content=raw,
                content_hash=hashlib.sha256(raw).hexdigest(),
                domain=Domain.IMAGE,
                content_type=ContentType.JPEG,  # or ContentType.PNG
            )
```

The rating UI automatically renders image chunks as `<img>` elements. The LLM judge sends image bytes to Ollama via its `images` field — ensure the project's LLM model is vision-capable (e.g. `llava:7b`).

---

## Help page

Every plugin can ship its own user-facing help page. Verdikt displays it in the **Help** section of the UI under the plugin's name.

### How it works

1. Create a Markdown file next to your plugin module (e.g. `myplugin_help.md`).
2. Override the `help_markdown()` classmethod on your plugin class to return its contents:

```python
@classmethod
def help_markdown(cls) -> str:
    from pathlib import Path
    return (Path(__file__).parent / "myplugin_help.md").read_text(encoding="utf-8")
```

The default implementation (on `PluginBase`) returns an empty string, which results in no help section being shown for your plugin.

### What to write

The help file should document what your plugin does from a **user's perspective**:

- What content it fetches and how to configure it
- Any credentials or API keys required
- How to keep content up to date
- Supported file types or formats (if applicable)
- Rate limits, ToS notes, or other things users should know

**Do not** repeat technical implementation details that belong in this developer guide.

The Markdown renderer in the UI supports headings (`#`, `##`, `###`), paragraphs, **bold**, *italic*, `inline code`, fenced code blocks, unordered and ordered lists, blockquotes (`> `), tables (`|`), horizontal rules (`---`), and links (`[text](url)`).

### Keeping it up to date

Because the Markdown file lives inside your plugin package, updating the help page is a normal package release — no changes to Verdikt core are required.

---

## Packaging checklist

- [ ] `plugin_name` is set as a class attribute and matches the `entry_points` key
- [ ] `supported_domains` is set if the plugin only applies to specific domains (omit for all-domain plugins)
- [ ] `config_schema()` returns valid JSON Schema with `"required"` for all mandatory fields
- [ ] Every `MaterialItem` has `source_path` set (for upsert detection)
- [ ] Every `MaterialItem` has `content_hash` set (for change detection)
- [ ] `content` is `str` for text, `bytes` for images
- [ ] `fetch()` is a generator (`yield`, not `return list`)
- [ ] The entry point is declared in `pyproject.toml` under `verdikt.plugins`
- [ ] Rate limits and ToS respected; `User-Agent` identifies your plugin
