# Verdikt

A local-first, open-source preference learning platform. Rate content samples across configurable dimensions, build a personal preference model, and receive recommendations with per-dimension explanations — entirely on your machine.

## How it works

1. **Register & log in** — create an account; all your data is isolated and encrypted per user
2. **Ingest** — upload files via the UI or drop them into your storage directory; select what to ingest
3. **Pipeline** — Verdikt chunks, embeds, and clusters your content automatically
4. **Rate** — score representative chunks on dimensions you define (prose quality, atmosphere, pacing, etc.) using keyboard shortcuts for speed
5. **Crystallise** — once you have enough ratings, a local LLM synthesises a structured preference profile
6. **Confirm AI ratings** — after a profile exists, AI rates new chunks in the background; review and confirm them to rapidly build confidence

## Requirements

- Python 3.11+
- Node 18+
- [Ollama](https://ollama.com) running locally with a model pulled, e.g.:

```bash
ollama pull llama3.1:8b
```

## Docker deployment (recommended for servers)

Requires Docker with Compose. Ollama must be running on the host.

```bash
docker compose up -d
```

The app is available at `http://localhost:8765`. Data persists in the `verdikt-data` Docker volume.

To point at a remote Ollama instance, set `VERDIKT_INFERENCE__OLLAMA_BASE_URL` in `docker-compose.yml` or via an environment variable.

HuggingFace model files (sentence-transformers) are cached in the data volume at `.cache/huggingface` and downloaded automatically on first use.

## Setup (local development)

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

Open `http://localhost:5173`. You will be redirected to the registration page on first use.

### First run

1. Register an account at `/register`
2. Create a project — give it a name and configure rating dimensions (or keep the defaults)
3. Click **Browse & Ingest Files** to upload files and select what to ingest
4. Click **Run Pipeline** on the dashboard — watch chunk / embed / cluster progress live
5. Click **Rate Chunks** and score passages with the keyboard
6. Once the dashboard shows enough ratings, open **Profile** and click **Crystallise**
7. Start AI Rating from the dashboard to score remaining chunks automatically; then use **Confirm AI ratings** mode to review them and build profile confidence

### Rating keyboard shortcuts

| Key | Action |
|---|---|
| `1`–`5` | Score the active dimension |
| `Tab` / `→` | Next dimension |
| `Shift+Tab` / `←` | Previous dimension |
| `Enter` | Submit (all dimensions must be scored) |
| `s` | Skip this chunk |

## Profile confidence

After a preference profile exists, Verdikt scores new chunks in the background while you rate. When you submit your own score, a flash bar shows what the AI would have rated and how closely the scores matched. This match rate accumulates as **AI accuracy** — a percentage shown on the dashboard.

- **≥ 90%** — profile is predictive; AI and human ratings agree closely
- **< 90% (after 5+ confirmations)** — an amber badge prompts re-crystallisation with more data

Accuracy resets with each new profile version so you can track improvement over time.

## Export and import

Projects can be exported and imported as JSON from the project list:

- **Export** — downloads a `verdikt-export-<project>.json` file containing the project, all materials, ratings, profiles, and plugin configs (binary content excluded)
- **Import** — creates a new project from an export file; materials are marked `ingested` and need the pipeline re-run to regenerate chunks and embeddings

## File storage

Files for ingest are managed per-user at `~/.verdikt/users/<user_id>/files/`. Two ways to add files:

- **Upload via the UI** — click "Browse & Ingest Files" on any project dashboard, then "Upload files"
- **Drop files directly** — copy files into `~/.verdikt/users/<user_id>/files/` (or a subdirectory); they appear in the browser immediately

**Supported formats:** `.txt`, `.md`, `.html`, `.epub`, `.pdf`, `.rtf`

Files are stored encrypted at rest using AES-256-GCM. On disk each file is an opaque UUID-named blob with no extension or readable metadata; filenames, paths, and sizes are kept only in the per-user SQLCipher database. A server admin with filesystem access cannot read file content or determine what files a user has uploaded. Existing plaintext files are migrated automatically on first login after an upgrade.

The storage root is configurable via `VERDIKT_DATA_DIR` (defaults to `/var/lib/verdikt`). User spaces can be placed on a separate volume with `VERDIKT_USERS_DIR`.

## Project settings

Each project has independently configurable:

- **Name and description**
- **Rating dimensions** — name, description, and weight; dimensions with existing ratings show a warning if you change their meaning
- **Crystallisation threshold** — minimum non-skipped ratings required before crystallisation
- **Chunk size** — min/max word count per chunk (affects pipeline output)
- **Min profile confidence** — accuracy threshold (default 90%) below which the dashboard prompts re-crystallisation

When a dimension is renamed, all existing ratings are migrated to the new name automatically.

## Configuration

All configuration is via environment variables (prefix `VERDIKT_`):

| Variable | Default | Description |
|---|---|---|
| `VERDIKT_DATA_DIR` | `/var/lib/verdikt` | System data directory (auth.db, jwt_secret, logs) |
| `VERDIKT_USERS_DIR` | `$VERDIKT_DATA_DIR/users` | Per-user data root; can point to a separate volume |
| `VERDIKT_JWT_SECRET` | *(auto-generated)* | Secret for JWT signing; persisted to `$VERDIKT_DATA_DIR/jwt_secret` if not set |
| `VERDIKT_ROOT_PATH` | *(empty)* | ASGI subpath prefix (e.g. `/verdikt`) |
| `VERDIKT_CORS_ORIGINS` | `http://localhost:5173` | Allowed CORS origins |
| `VERDIKT_INFERENCE__OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `VERDIKT_INFERENCE__OLLAMA_MODEL` | `llama3.1:8b` | Model used for crystallisation and AI rating |
| `VERDIKT_INFERENCE__EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |

## Admin

The first registered user is automatically an admin. Admins can manage users at `/admin/users`:

- View all accounts with registration date and status
- Block / unblock users
- Delete users (removes their account and all data)

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

## Migrating existing data

If you have data from a pre-auth version of Verdikt, run the migration script to move it under a user account:

```bash
python3 backend/scripts/migrate_to_user.py --email you@example.com
```

This creates the user account (prompting for a password), copies the existing database, files, and vectors into the per-user directory, encrypts the database, and creates a timestamped backup of the original.

## Running tests

```bash
cd backend

# Unit tests only (no infrastructure required)
pytest -m "not infra" -q

# Full suite (requires Ollama + sentence-transformers model download)
pytest -q
```

## Data directory layout

```
/var/lib/verdikt/           VERDIKT_DATA_DIR  — system files
  auth.db                   Global users table (unencrypted)
  jwt_secret                Auto-generated JWT signing key
  verdikt.log               Application log
  backups/                  Pre-migration backups (if migration script was run)

/var/lib/verdikt/users/     VERDIKT_USERS_DIR — per-user spaces (default: data_dir/users)
  <user_id>/
    verdikt.db              Per-user SQLite database (SQLCipher encrypted)
    chroma/                 Per-user ChromaDB vector store
    files/                  Per-user upload root (AES-256-GCM encrypted UUID blobs)
      <uuid4>               Encrypted file content — opaque, no extension or readable name
      <uuid4>               ...
```

`VERDIKT_USERS_DIR` can point to a separate volume (e.g. a large data disk) while `VERDIKT_DATA_DIR` stays on the system volume.

To start fresh for a specific user, delete `VERDIKT_USERS_DIR/<user_id>/`. Directories and schema are recreated automatically on next use.

## Project structure

```
backend/          Python package — pipeline, storage, plugins, inference, API, CLI
frontend/         React + TypeScript web UI
docs/             Developer guides
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
