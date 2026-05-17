# Verdikt

A local-first, open-source preference learning platform. Rate content samples across configurable dimensions, build a personal preference model, and receive recommendations with per-dimension explanations — entirely on your machine.

## How it works

1. **Register & log in** — create an account; all your data is isolated and encrypted per user
2. **Ingest** — upload files, point at a storage directory, or connect to a remote source like Immich; select what to ingest
3. **Pipeline** — Verdikt chunks, embeds, and clusters your content automatically
4. **Rate** — score representative chunks on dimensions you define (prose quality, composition, atmosphere, etc.) using keyboard shortcuts for speed
5. **Crystallise** — once you have enough ratings, a local LLM synthesises a structured preference profile
6. **Confirm AI ratings** — after a profile exists, AI rates new chunks in the background; review and confirm them to rapidly build profile confidence
7. **Inspect works** — open any work's detail view to see its chunks, ratings, and AI-generated descriptions; collapse chunks you've reviewed, or trigger AI rating on individual chunks directly from the detail view

## Requirements

- Python 3.11+
- Node 18+
- [Ollama](https://ollama.com) running locally with at least one model pulled

```bash
# Text projects — any general-purpose LLM
ollama pull llama3.1:8b

# Image projects — a vision-capable model
ollama pull llava:7b
```

## Docker deployment (recommended for servers)

Requires Docker with Compose. Ollama must be running on the host.

```bash
docker compose up -d
```

The app is available at `http://localhost:8765`. Data persists in the `verdikt-data` Docker volume.

To point at a remote Ollama instance, set `VERDIKT_INFERENCE__OLLAMA_BASE_URL` in `docker-compose.yml` or via an environment variable.

HuggingFace model files (sentence-transformers and CLIP) are cached in the data volume at `.cache/huggingface` and downloaded automatically on first use.

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

1. Register an account at `/register` — the first registered user becomes admin
2. Go to **Admin › Models**, click **Sync from Ollama** to discover installed models
3. Enable the models you want and set a default LLM for each domain you plan to use
4. Create a project — choose a domain (Text or Image), name it, configure rating dimensions
5. Click **Browse & Ingest Files** to upload files, or configure a content plugin (AO3, Royal Road, Immich) via the **Plugins** section on the dashboard
6. Click **Run Pipeline** on the dashboard — watch chunk / embed / cluster progress live
7. Click **Rate Chunks** and score passages with the keyboard
8. Once the dashboard shows enough ratings, open **Profile** and click **Crystallise**
9. Start AI Rating from the dashboard to score remaining chunks automatically; then use **Confirm AI ratings** mode to review them and build profile confidence

For contextual help at any time, open the **Help** page from the settings menu (☰) in the top right.

### Rating keyboard shortcuts

| Key | Action |
|---|---|
| `1`–`5` | Score the active dimension |
| `Tab` / `→` | Next dimension |
| `Shift+Tab` / `←` | Previous dimension |
| `Enter` | Submit (all dimensions must be scored) |
| `s` | Skip this chunk |

## Domains

Verdikt supports two content domains. The domain is set when a project is created and cannot be changed.

### Text

- **Embedding**: sentence-transformers (bundled, no Ollama required for embedding)
- **LLM**: any Ollama model; set the default for the text domain in Admin › Models
- **Chunking**: paragraph-aware word-count windows (configurable min/max per project)
- **Supported formats**: `.txt`, `.md`, `.html`, `.epub`, `.pdf`, `.rtf`

### Image

- **Embedding**: OpenAI CLIP (`openai/clip-vit-base-patch32`, downloaded from HuggingFace on first use); not configurable per-project
- **LLM**: must be a vision-capable model (e.g. `llava:7b`, `llama3.2-vision`); set the default for the image domain in Admin › Models
- **Chunking**: one image = one chunk; chunk size settings do not apply
- **Supported formats**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`, `.tiff`

Image content is displayed as thumbnails throughout the rating and recommendation interfaces.

## Model management (admin)

Admins manage the model catalog at **Admin › Models**. The catalog controls which models users can select per project and sets domain defaults. Three model sources are supported: local Ollama, Venice.ai (hosted), and OpenRouter (hosted gateway).

### Local Ollama models

1. In the **Ollama** card, click **↻ Sync from Ollama** — discovers all locally installed models and adds them to the catalog with auto-detected type (LLM / Embedding) and domain (Text / Image / Any)
2. **Enable** models you want users to be able to select; disabled models are hidden in project settings
3. **Edit** a model to adjust its type, domain classification, display name, or description
4. **Set default** — mark one LLM per domain as the default; this model is pre-selected when creating a new project in that domain. A domain with no enabled LLM is unavailable for new projects.

**Ollama Bearer auth (optional)** — if your Ollama instance is behind a reverse proxy that requires authentication, enter a Bearer token in the **Ollama** card. When set, all Verdikt requests to Ollama (LLM calls, embedding, and catalog sync) include `Authorization: Bearer <token>`. Standard Ollama installs require no key.

**Sentence-transformer embedding models** — these are not discoverable via Ollama sync. Add them manually by clicking **+ Add model** (currently only in the API; manage via Admin › Models). The bundled default (`all-MiniLM-L6-v2`) is always available without registration.

### Venice.ai (hosted LLMs + embeddings)

[Venice.ai](https://venice.ai) provides an OpenAI-compatible API for LLM inference and text embeddings, with a focus on privacy (prompts are not logged by default).

1. Enter your Venice API key in the **Venice.ai** card and click **Save**
2. Click **↻ Sync from Venice** to populate the catalog with available Venice models
3. Enable and set defaults as with Ollama models

Venice models are shown with a purple **Venice** badge in the model list. When a Venice model is selected for a project, a cost notice is shown in the project settings dialog.

To get an API key: sign up at [venice.ai](https://venice.ai) and generate a key in your account settings.

### OpenRouter (hosted LLM gateway)

[OpenRouter](https://openrouter.ai) provides a unified API gateway to hundreds of hosted models from Anthropic, Google, Meta, Mistral, and many others.

1. Enter your OpenRouter API key in the **OpenRouter** card and click **Save**
2. Click **↻ Sync from OpenRouter** to populate the catalog with available models
3. Enable and set defaults as with Ollama models

OpenRouter models are shown with a teal **OpenRouter** badge. Pricing information (cost per million tokens) is displayed in the model list and in the project settings dialog when an OpenRouter model is selected.

OpenRouter does not support embeddings — all embedding models remain local (sentence-transformers or Ollama embedding models).

To get an API key: sign up at [openrouter.ai](https://openrouter.ai) and generate a key in your account.

### Model domain classification

| Domain | Meaning |
|---|---|
| Text | Appears in text-project LLM picker only |
| Image | Appears in image-project LLM picker only |
| Any | Appears in all domains (vision LLMs capable of both text and image) |

Models containing "embed" in their name are auto-classified as Embedding / Text on sync. Models with CLIP in their family or vision in their capabilities list are auto-classified as LLM / Any. You can override any classification via **Edit**.

## Profile confidence

After a preference profile exists, Verdikt scores new chunks in the background while you rate. When you submit your own score, a flash bar shows what the AI would have rated and how closely the scores matched. This match rate accumulates as **AI accuracy** — a percentage shown on the dashboard.

- **≥ 90%** — profile is predictive; AI and human ratings agree closely
- **< 90% (after 5+ confirmations)** — an amber badge prompts re-crystallisation with more data

Accuracy resets with each new profile version so you can track improvement over time.

## Work detail view

Click any work title on the project dashboard to open its detail view. The view shows metadata (source, ingest date, URL, file path) and all chunks with their current ratings.

- **Collapse chunks** — click a chunk header to show or hide the content. The AI-generated description (if available) remains visible below the header even when collapsed.
- **Rate or edit** — click the rating pill on a rated chunk to open the edit dialog; click **+ rate** on an unrated chunk to add a rating.
- **↺ AI button** — triggers AI rating for a single chunk. Works whether the chunk is unrated or already rated; re-rating a chunk replaces the previous AI score. The button spins while the LLM is running and the view refreshes automatically when done.
- **AI badge on human ratings** — if a human rating has replaced an AI rating for a chunk, a small dashed-border `AI` badge appears next to `Human` to indicate both scores exist.
- **Remove work** — the footer of the detail view has a **Remove work** button that deletes the work, its chunks, and all associated ratings.

## Export and import

Projects can be exported and imported as JSON from the project list:

- **Export** — downloads a `verdikt-export-<project>.json` file containing the project, all materials, ratings, profiles, and plugin configs (binary content excluded)
- **Import** — creates a new project from an export file; materials are marked `ingested` and need the pipeline re-run to regenerate chunks and embeddings

## Content source plugins

Verdikt fetches content via **plugins** — each plugin knows how to pull from one kind of source. A project can have multiple plugins active simultaneously, each configured independently. New plugins can be installed as Python packages via the plugin entry-points system (see `docs/plugin-developer-guide.md`).

### File Drop (text & image)

Upload files directly or drop them into your user storage directory on the server. Files are stored encrypted at rest using AES-256-GCM — on disk each file is an opaque UUID-named blob; filenames and paths are kept only in your per-user SQLCipher database.

**Upload via the UI** — click "Browse & Ingest Files" on any project dashboard, then "Upload files".  
**Drop files directly** — copy files into `$VERDIKT_USERS_DIR/<user_id>/files/` on the server; they appear in the browser immediately.

**Text formats:** `.txt`, `.md`, `.html`, `.epub`, `.pdf`, `.rtf`  
**Image formats:** `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`, `.tiff`

Ingest is idempotent: files already in the project are only updated when their content changes. For full details, open the **Help** page in the plugin config dialog.

### AO3 (text)

Fetch fan fiction from [Archive of Our Own](https://archiveofourown.org). Browse or search AO3, copy the URL (e.g. `https://archiveofourown.org/tags/Original%20Work/works`), and paste it into the plugin's **Search URLs** list. Each URL has its own **Max works** cap.

Works are sampled rather than stored in full: roughly 10% of paragraphs are retained per work, selected with a Gaussian distribution centred on the middle of the work. This is enough to learn preferences without holding a copy of the original.

**Authentication** (optional) — provide your AO3 credentials to access works visible to registered users. Credentials are stored encrypted in your project config.

| Variable | Default | Effect |
|---|---|---|
| `VERDIKT_AO3_SAMPLE_RATE` | `0.10` | Fraction of paragraphs to retain |
| `VERDIKT_AO3_SAMPLE_STDDEV` | `1.5` | Gaussian spread; higher = more even coverage |
| `VERDIKT_AO3_REQUEST_DELAY` | `5.0` | Seconds between requests (hard minimum 3 s) |

AO3 is a community-run site. The delay minimum is intentional and cannot be configured below 3 seconds. For full details, open the **Help** page in the plugin config dialog.

### Royal Road (text)

Fetch web fictions from [Royal Road](https://www.royalroad.com). Three source types can be combined in one project:

- **Fiction URLs** — paste direct links to specific fiction pages
- **Search / Browse URLs** — copy a Royal Road browse or tag page URL; set a **Max** cap per URL
- **Following list** — enable **Import followed fictions** and provide your credentials to pull from your follow list

Long fictions are sampled in two stages: first ~30% of chapters are selected (Gaussian-weighted toward the middle), then ~20% of the downloaded paragraphs are retained. Sampling is deterministic per fiction ID.

| Variable | Default | Effect |
|---|---|---|
| `VERDIKT_RR_CHAPTER_RATE` | `0.30` | Fraction of chapters to download |
| `VERDIKT_RR_CHAPTER_STDDEV` | `1.5` | Gaussian spread for chapter selection |
| `VERDIKT_RR_SAMPLE_RATE` | `0.20` | Fraction of paragraphs to retain |
| `VERDIKT_RR_SAMPLE_STDDEV` | `1.5` | Gaussian spread for paragraph sampling |
| `VERDIKT_RR_REQUEST_DELAY` | `2.0` | Seconds between requests (hard minimum 1 s) |

For full details, open the **Help** page in the plugin config dialog.

### Immich (image)

Fetch photos from a self-hosted [Immich](https://immich.app) instance (v1.90+). Configure it from the project dashboard under **Plugins**:

- **Immich URL** — base URL of your instance (e.g. `http://192.168.1.10:2283`)
- **API Key** — generate one in Immich › Account Settings › API Keys
- **Image storage** — `preview` (~200 KB, default), `thumbnail` (~30 KB), or `none` (always fetch live; requires Immich reachable at rating time)
- **Sources** — one or more of: `album` (by album UUID), `search` (metadata query), or `all` (entire library up to a cap)

After rating and running AI Rating, the **Write back** button pushes Verdikt scores (as Immich star ratings 1–5) and LLM-generated descriptions back to each photo asset. For full details, open the **Help** page in the plugin config dialog.

## Security and privacy

**Encrypted at rest** — all user files and database content are encrypted per-user with AES-256-GCM (files) and SQLCipher (database). The encryption key is derived from the user's login password via Argon2id and is never written to disk. A server administrator with filesystem access cannot read content, filenames, or preference data without the user's password.

**What is not encrypted** — the embedding database (ChromaDB) does not support encryption and remains unencrypted on disk. It contains only numerical vectors and opaque internal IDs — no filenames, no text content, no usernames. Reconstructing readable content from raw embedding vectors requires reversing the neural network that produced them, which is not a realistic attack for the models Verdikt uses. For deployments where even this residual exposure is unacceptable, full-disk encryption at the OS level (e.g. LUKS on Linux) covers the ChromaDB directory alongside everything else.

**No logging of content** — Verdikt does not log content, filenames, URLs, or email addresses. Log output contains only counts, status codes, UUIDs, and error messages.

**Hosted models** — when Venice.ai or OpenRouter models are configured, content sent to them for LLM inference leaves your server. Venice.ai models marked **Private** do not retain prompts; models marked **Anonymized** may retain them in anonymized form. Check the badge shown in Admin › Models and in the project settings dialog before selecting a hosted model for sensitive content.

## Project settings

Each project has independently configurable:

- **Name and description**
- **Rating dimensions** — name, description, and weight; dimensions with existing ratings show a warning if you change their meaning
- **Crystallisation threshold** — minimum non-skipped ratings required before crystallisation
- **Chunk size (text projects only)** — min/max word count per chunk; not shown for image projects since each image is always one chunk
- **Language model** — override the domain default for this project; choose from enabled catalog models
- **Embedding model (text projects only)** — override the bundled default; changing this after the pipeline has run requires re-running the pipeline to re-embed all works

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
| `VERDIKT_INFERENCE__OLLAMA_MODEL` | `llama3.1:8b` | Fallback LLM when no catalog default is set for a domain |
| `VERDIKT_INFERENCE__EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Fallback sentence-transformers embedding model for text projects |
| `VERDIKT_INFERENCE__CLIP_MODEL` | `openai/clip-vit-base-patch32` | CLIP model for image embedding (HuggingFace model ID) |
| `VERDIKT_GOOGLE_CLIENT_ID` | *(empty)* | Google OAuth client ID; leave unset to disable Google login |
| `VERDIKT_GOOGLE_CLIENT_SECRET` | *(empty)* | Google OAuth client secret |
| `VERDIKT_GITHUB_CLIENT_ID` | *(empty)* | GitHub OAuth App client ID; leave unset to disable GitHub login |
| `VERDIKT_GITHUB_CLIENT_SECRET` | *(empty)* | GitHub OAuth App client secret |
| `VERDIKT_OAUTH_REDIRECT_BASE` | `http://localhost:8765` | Base URL used in OAuth callback URIs |
| `VERDIKT_AO3_SAMPLE_RATE` | `0.10` | AO3: fraction of paragraphs to retain per work |
| `VERDIKT_AO3_SAMPLE_STDDEV` | `1.5` | AO3: Gaussian spread for paragraph sampling |
| `VERDIKT_AO3_REQUEST_DELAY` | `5.0` | AO3: seconds between HTTP requests (hard minimum 3 s) |
| `VERDIKT_RR_CHAPTER_RATE` | `0.30` | Royal Road: fraction of chapters to download per fiction |
| `VERDIKT_RR_CHAPTER_STDDEV` | `1.5` | Royal Road: Gaussian spread for chapter selection |
| `VERDIKT_RR_SAMPLE_RATE` | `0.20` | Royal Road: fraction of paragraphs to retain from downloaded chapters |
| `VERDIKT_RR_SAMPLE_STDDEV` | `1.5` | Royal Road: Gaussian spread for paragraph sampling |
| `VERDIKT_RR_REQUEST_DELAY` | `2.0` | Royal Road: seconds between HTTP requests (hard minimum 1 s) |

LLM and embedding model defaults are primarily managed through the Admin › Models catalog. The environment variables above serve as global fallbacks when no catalog default has been configured.

## Token usage and budget

LLM calls (AI rating, profile crystallisation, recommendation) consume tokens. Admins can apply limits to prevent runaway usage on shared servers.

### Viewing usage

Open **Token Usage** from the settings menu (☰). The page shows your current balance, daily / weekly / monthly / all-time totals, and a per-project breakdown.

### Admin grant management

In **Admin › Users**, select a user and:

- **Set daily limit** — controls the token grant issued each day (`null` = unlimited)
- **Issue a one-time grant** — add tokens that expire on a chosen date or never
- **Set expiry days** — how many days each daily grant stays valid before it expires

When a user's balance reaches zero, they receive HTTP 402 on the next LLM-dependent request. Issue a grant or increase their daily limit to restore access.

## Admin

The first registered user is automatically an admin. Admins have access to:

### Users (`/admin/users`)

- View all accounts with registration date and status
- Block / unblock users — blocked users cannot log in
- Delete users (removes their account and all data)
- Promote / demote admin status — the founding admin (first registered user) cannot be demoted
- Manage token usage limits and issue one-time token grants

### Models (`/admin/models`)

- Sync the local Ollama model catalog; optionally configure a Bearer token for authenticated Ollama instances
- Sync hosted model catalogs from Venice.ai and OpenRouter after entering API keys
- Enable/disable models for user selection
- Set per-domain LLM defaults
- Edit model type, domain classification, display name, and description

## OAuth login

Verdikt supports sign-in via Google and GitHub. Set the following environment variables to enable each provider:

| Variable | Description |
|---|---|
| `VERDIKT_GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `VERDIKT_GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `VERDIKT_GITHUB_CLIENT_ID` | GitHub OAuth App client ID |
| `VERDIKT_GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret |
| `VERDIKT_OAUTH_REDIRECT_BASE` | Base URL for OAuth callbacks (default: `http://localhost:8765`) |

When at least one provider is configured, the login page shows the corresponding "Sign in with …" buttons alongside the password form. OAuth users have no password and use an encrypted DB key that is wrapped with a server-side HKDF key derived from the JWT secret.

To set up a Google OAuth client: go to the [Google Cloud Console](https://console.cloud.google.com/), create an OAuth 2.0 client, and add `<VERDIKT_OAUTH_REDIRECT_BASE>/api/auth/oauth/google/callback` as an authorised redirect URI.

For GitHub: create an OAuth App in GitHub Settings › Developer settings; set the callback URL to `<VERDIKT_OAUTH_REDIRECT_BASE>/api/auth/oauth/github/callback`.

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

# Full suite (requires Ollama + model downloads)
pytest -q
```

## Data directory layout

```
/var/lib/verdikt/           VERDIKT_DATA_DIR  — system files
  auth.db                   Global users + model catalog (unencrypted)
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
