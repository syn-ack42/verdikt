# Verdikt

A local-first, open-source preference learning platform. Rate content samples across configurable dimensions, build a personal preference model, and receive recommendations with per-dimension explanations — entirely on your machine.

## How it works

1. **Ingest** — upload files or drop them directly into the storage directory; select what to ingest via the browser
2. **Pipeline** — Verdikt chunks, embeds, and clusters your content automatically
3. **Rate** — score representative chunks on dimensions you define (prose quality, atmosphere, pacing, etc.) using keyboard shortcuts for speed
4. **Crystallise** — once you have enough ratings, a local LLM synthesises a structured preference profile
5. **Recommend** — new material is scored against your profile with a per-dimension breakdown *(coming in Milestone 4)*

## Requirements

- Python 3.11+
- Node 18+
- [Ollama](https://ollama.com) running locally with a model pulled, e.g.:

```bash
ollama pull llama3.1:8b
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e backend/
```

## Running the web UI

```bash
# Terminal 1 — API server (default port 8765)
verdikt serve --reload

# Terminal 2 — frontend dev server
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`.

### Typical workflow

1. Create a project — give it a name and configure rating dimensions (or keep the defaults)
2. Click **Browse & Ingest Files** to upload files and select what to ingest
3. Click **Run Pipeline** on the dashboard — watch chunk / embed / cluster progress live
4. Click **Rate Chunks** and score passages with the keyboard
5. Once the dashboard shows enough ratings, open **Profile** and click **Crystallise**

### Rating keyboard shortcuts

| Key | Action |
|---|---|
| `1`–`5` | Score the active dimension |
| `Tab` / `→` | Next dimension |
| `Shift+Tab` / `←` | Previous dimension |
| `Enter` | Submit (all dimensions must be scored) |
| `s` | Skip this chunk |

## File storage

Files for ingest are managed in `~/.verdikt/user_files/`. Two ways to add files:

- **Upload via the UI** — click "Browse & Ingest Files" on any project dashboard, then "Upload files"
- **Drop files directly** — copy files into `~/.verdikt/user_files/` (or a subdirectory); they appear in the browser immediately

**Supported formats:** `.txt`, `.md`, `.html`, `.epub`, `.pdf`, `.rtf`

The storage root is configurable via `VERDIKT_DATA_DIR` (defaults to `~/.verdikt`). The abstraction is designed to support remote backends such as S3 in a future release.

## Project settings

Each project has independently configurable:

- **Name and description**
- **Rating dimensions** — name, description, and weight; dimensions with existing ratings show a warning if you change their meaning
- **Crystallisation threshold** — minimum non-skipped ratings required before crystallisation
- **Chunk size** — min/max word count per chunk (affects pipeline output)

When a dimension is renamed, all existing ratings are migrated to the new name automatically.

## Configuration

All configuration is via environment variables (prefix `VERDIKT_`):

| Variable | Default | Description |
|---|---|---|
| `VERDIKT_DATA_DIR` | `~/.verdikt` | Root data directory |
| `VERDIKT_ROOT_PATH` | *(empty)* | ASGI subpath prefix (e.g. `/verdikt`) |
| `VERDIKT_CORS_ORIGINS` | `http://localhost:5173` | Allowed CORS origins |
| `VERDIKT_INFERENCE__OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `VERDIKT_INFERENCE__OLLAMA_MODEL` | `llama3.1:8b` | Model used for crystallisation |
| `VERDIKT_INFERENCE__EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |

## CLI reference

The CLI is useful for bulk operations and scripting. All project arguments accept either the UUID or the project name.

### Projects

```bash
verdikt project create "dark-fantasy" --description "Dark fantasy fiction" --domain text
verdikt project list
verdikt project show "dark-fantasy"
verdikt project works "dark-fantasy"
verdikt project works "dark-fantasy" --phase clustered
verdikt project delete "dark-fantasy" --yes
```

### Ingesting content

```bash
# Ingest a directory (idempotent: new files added, changed files updated, unchanged skipped)
verdikt ingest <project> ./my-books/

# Add or update a single file
verdikt add <project> /path/to/book.epub
```

### Pipeline

```bash
verdikt pipeline run "dark-fantasy"

# Re-process a single work (resets to ingested, re-runs full pipeline)
verdikt pipeline run-work "dark-fantasy" 2
verdikt pipeline run-work "dark-fantasy" /abs/path/to/book.epub
```

### Removing content

```bash
# Removes the work, its chunks, vectors, and all associated ratings
verdikt remove "dark-fantasy" 3
verdikt remove "dark-fantasy" /abs/path/to/book.epub
```

## Running tests

```bash
cd backend

# Unit tests only (no infrastructure required)
pytest -m "not infra" -q

# Full suite (requires Ollama + sentence-transformers model download)
pytest -q

# Ollama crystallisation integration test only
pytest -m infra tests/test_crystalliser_infra.py -v
```

## Data directory layout

```
~/.verdikt/
  verdikt.db        SQLite database (projects, works, chunks, ratings, profiles)
  chroma/           ChromaDB vector store (one collection per project)
  projects/         Per-project data
  user_files/       Upload root for the web UI file browser
```

To start fresh:

```bash
rm -rf ~/.verdikt
```

The directory and schema are recreated automatically on next use.

## Project structure

```
backend/          Python package — pipeline, storage, plugins, inference, API, CLI
frontend/         React + TypeScript web UI
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
