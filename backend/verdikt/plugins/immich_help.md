# Immich Plugin

Fetches photos from a self-hosted [Immich](https://immich.app) instance and brings them into a Verdikt image project for rating and preference learning.

## Requirements

- A running Immich instance (v1.90+)
- An API key created in Immich › Account Settings › API Keys

## Configuration

| Field | Description |
|---|---|
| **Immich URL** | Base URL of your Immich instance, e.g. `http://192.168.1.10:2283` |
| **API Key** | Your Immich API key (read + write access required for writeback) |
| **Image storage** | How much image data to store in Verdikt (see below) |
| **Sources** | One or more source definitions (album, search query, or all photos) |

## Image storage modes

| Mode | What is stored | Immich connectivity |
|---|---|---|
| **preview** (default) | ~200 KB JPEG (1280 px) fetched once at ingest | Not needed after ingest |
| **thumbnail** | ~30 KB JPEG (250 px) fetched once at ingest | Not needed after ingest |
| **none** | Nothing stored — bytes fetched on every access | Required at all times |

`preview` is recommended. It stores enough quality for the LLM vision judge to score images accurately while keeping storage modest. Use `thumbnail` if storage space is a concern. Use `none` only if you want zero local storage and can guarantee Immich is always reachable.

## Source types

### Album
Fetches all assets from a specific Immich album.

Set **Source type** to `album` and provide the album's UUID (find it in the Immich album URL: `.../albums/<uuid>`).

### Search
Fetches assets matching an Immich metadata search query.

Set **Source type** to `search` and provide a text query. Immich searches across file names, descriptions, and metadata.

### All photos
Fetches photos from your entire library, up to **Max items**.

Set **Source type** to `all`. Useful for getting a broad sample for preference learning.

## Writeback

After rating photos and running AI Rating (which generates descriptions), you can write data back to Immich:

- **Ratings as star ratings** — the weighted average of all dimension scores is converted to an Immich star rating (1–5 stars) and written back to each asset.
- **Descriptions** — the LLM-generated 1–2 sentence description is appended to the asset's Immich description under a `#verdikt:` prefix. Re-running writeback replaces the existing `#verdikt:` line rather than duplicating it.

Click **Write back** on the project dashboard to trigger writeback. Both options are independent checkboxes.

> Writeback requires the API key to have **write** access. Immich ratings and descriptions updated by Verdikt are visible to all users of that Immich instance.

## Tips

- Start with a single album or a focused search query to build an initial preference model, then expand to more sources.
- After running the full pipeline (ingest → pipeline → AI rating), crystallise your profile before using writeback — the descriptions are generated during AI rating.
- The plugin respects `max_items` per source to avoid accidentally ingesting thousands of photos in one go.
