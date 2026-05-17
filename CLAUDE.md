# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Verdikt is a local-first, open-source **preference learning platform**. Users rate content samples across configurable dimensions; the system builds a preference model and recommends new material with per-dimension explanations. The full specification is in `verdikt_brief.md`.

## Tech stack

- **Backend**: Python, FastAPI, SQLAlchemy + SQLite (SQLCipher for per-user encryption), Prefect (pipeline orchestration)
- **Frontend**: React + TypeScript, Vite, TanStack Query
- **ML**: Ollama (local LLM), sentence-transformers (text embeddings), OpenAI CLIP via `transformers` (image embeddings), ChromaDB (vector store)
- **Auth**: HttpOnly JWT cookie (`SameSite=Lax`), Argon2id password hashing
- **Plugin system**: Python packages registered via `entry_points`

## Architecture

Five layers with strict separation of concerns:

1. **Plugin layer** — fetches and normalises raw content into `MaterialItem` objects. Plugins know nothing about preference learning. Each plugin declares a JSON Schema config; the UI renders config forms from it automatically. Plugins declare `supported_domains: ClassVar[frozenset[Domain]]` to restrict which project domains they appear in (e.g. AO3 is text-only; Storage plugin supports text and image).
2. **Pipeline layer** — processes `MaterialItem`s through phases: `ingest → chunk → embed → cluster → rate → crystallise → evaluate → recommend`. Orchestrated by Prefect with `cache_policy=NO_CACHE` on all tasks (PipelineRunner is not serialisable). Phases are idempotent. This layer calls storage interfaces, never SQLite directly.
3. **Storage layer** — SQLite via SQLAlchemy for structured data; ChromaDB (one collection per project) for vectors; user files encrypted at rest via `EncryptedStorageBackend` (AES-256-GCM, UUID-named blobs, manifest in per-user DB). Exposed through interfaces so the pipeline layer is decoupled from implementation. User DB engines use `NullPool` to prevent connection sharing across concurrent requests.
4. **Inference layer** — Ollama for LLM tasks (profile crystallisation, LLM judging, explanations); sentence-transformers for text embeddings; `CLIPEmbedder` (`transformers.CLIPModel` + `CLIPImageProcessor`, `openai/clip-vit-base-patch32`) for image embeddings. `backend/verdikt/inference/resolver.py` is the single routing point: given a project and config it returns the correct `EmbedderBase` implementation. Per-project model overrides apply; domain determines embedder class.
5. **UI layer** — React + FastAPI. Three surfaces: project dashboard, rating interface, recommendation browser.

## Auth and per-user isolation

- **Global auth DB**: `$VERDIKT_DATA_DIR/auth.db` (default `/var/lib/verdikt/auth.db`) — plain SQLite, `users` table (id, email, argon2 hash, salt, is_admin, is_blocked) and `model_catalog` table (Ollama model registry with per-domain defaults)
- **Per-user data**: `$VERDIKT_USERS_DIR/<user_id>/` (default `data_dir/users/<user_id>/`) containing `verdikt.db` (SQLCipher-encrypted), `chroma/`, and `files/`
- **Two configurable roots**: `VERDIKT_DATA_DIR` for system files; `VERDIKT_USERS_DIR` for user spaces (can be a separate volume). Both default to `/var/lib/verdikt[/users]`.
- **JWT**: HttpOnly cookie `verdikt_token`; payload contains `sub=user_id` and `key=base64(derived_key)`; the derived key is Argon2id(password, salt) and never written to disk; the per-user DB is unreadable without it
- **File encryption**: `EncryptedStorageBackend` in `backend/verdikt/storage/files.py` — AES-256-GCM, key derived via HKDF-SHA256 from `db_key` with info tag `verdikt-file-encryption-v1`. On-disk files are opaque UUID blobs with no extension; the `file_manifest` table in `verdikt.db` maps UUIDs to virtual paths, original names, and metadata. `resolve()` decrypts to a temp file for parsers that need a real path; `cleanup()` removes temp files at request end. Plaintext files from before this feature are migrated automatically on first login.
- **`get_current_user()`** in `backend/verdikt/api/deps.py` — validates cookie, returns `User`; every route depends on this
- **First registered user** is auto-promoted to admin

## The MaterialItem contract

`MaterialItem` is the universal data structure crossing all layer boundaries. It is the interface third-party plugin authors depend on — treat it as a stable public API.

Fields:
- **Identity**: `uuid`, `project_id`
- **Provenance**: source plugin, URL, work title, author, work ID, chapter position
- **Content**: raw bytes or string, `domain` (`text`/`image`/`audio`), content type
- **Pipeline state**: whether chunks and embeddings have been generated

The plugin fills provenance and content. The pipeline fills everything else.

## Profile confidence

Confidence is prediction accuracy, not a rating count. After a profile exists:
- When a user enters the rating interface for an unrated chunk, `POST /ai-rating/preview` fires in the background (AbortController cancels it if the user submits first)
- When the user submits, the AI score is compared: `agreement = avg(1 - |ai - user| / 4)` per dimension
- `confirmed_count` and `score_sum` are accumulated on the `PreferenceProfile` row; `profile_confidence = score_sum / confirmed_count`
- Confidence resets to 0 on each new profile version (new crystallisation creates a new row)
- Below `min_profile_confidence` (default 0.9) after ≥5 confirmations, the dashboard shows an amber "re-crystallise" badge

## Key design constraints

**Privacy is non-negotiable.** Preference data never leaves the machine by default. Per-user SQLCipher encryption is required. This is the ethical basis for a potential monetisation model — violating it destroys the product.

**Domain abstraction from day one.** The chunker, embedder, and rating UI display are domain-specific components behind interfaces. Everything from clustering onward is domain-agnostic (operates on embedding vectors and rating scalars). Do not hardcode text-only assumptions even though the initial implementation is text-first.

**Pluggable everything.** New content sources, embedding models, and rating dimensions must drop in without touching core code.

**Project-scoped isolation.** Projects never share corpus, ratings, profiles, or recommendation history.

## Rating loop specifics

- Early sessions use diversity sampling (cluster-based) to maximise corpus coverage.
- Later sessions use uncertainty sampling (active learning) to target maximally informative chunks (switches after `crystallisation_threshold` ratings).
- Background AI preview fires on chunk load (normal mode, post-profile); result shown as flash bar after submit. Configurable via `VERDIKT_AI_PREVIEW_TEXT` (default `true`) and `VERDIKT_AI_PREVIEW_IMAGE` (default `false`); exposed to the frontend via `GET /api/config` → `AppConfig`. A per-project non-blocking mutex prevents stacked concurrent Ollama preview calls (returns 503 `preview_busy` if one is already in flight).
- Two rating modes: `normal` (rate new chunks) and `confirm_ai` (review AI-scored chunks). The dashboard Rate button navigates to `/rate?mode=confirm_ai` when unconfirmed AI chunks exist; `RatingInterface` reads this via `useSearchParams`.
- `GET /api/projects/{id}/ai-rating/status` includes `unconfirmed_ai_count` — number of AI ratings not yet confirmed by a human.
- A session of 20–30 ratings must feel fast: keyboard shortcuts, instant progression, no spinners between ratings.

## Recommendation engine

Two-stage: embedding similarity pre-filter (cheap) → LLM judge scoring surviving candidates per dimension against the preference profile (returns structured scores + natural language explanation). Output is always a ranked list with per-dimension breakdown, not bare scores.

## Docker deployment

The repo ships a production-ready multi-stage `Dockerfile` and `docker-compose.yml` at the repo root.

**Build stages:**
1. `node:20-alpine` — builds `frontend/` into `frontend/dist/`
2. `python:3.12-slim` + build deps — compiles `sqlcipher3` (needs `libsqlcipher-dev`) and all Python wheels; installs CPU-only PyTorch first to avoid the 2 GB CUDA download
3. Slim runtime — copies `/venv` from stage 2 and `frontend/dist` from stage 1; only `libsqlcipher0` needed at runtime

**Frontend serving:** `VERDIKT_FRONTEND_DIR` tells `app.py` where the built frontend lives. When set and the directory exists, it mounts `StaticFiles(html=True)` as a catch-all after all API routes, serving the SPA. The Dockerfile sets this to `/app/frontend/dist`.

**Data volume:** `/var/lib/verdikt` — holds auth.db, jwt_secret, logs, per-user databases, and the HuggingFace model cache (`HF_HOME=/var/lib/verdikt/.cache/huggingface`).

**Ollama:** expected on the host; `docker-compose.yml` sets `host.docker.internal:11434` with `extra_hosts: host.docker.internal:host-gateway` for Linux compatibility.

## Desktop distribution

`distribution/` is an isolated subdirectory (never imported by core) that ships three Docker Compose variants, a tkinter setup wizard, a pystray system-tray launcher, and platform installer scripts.

### Compose variants

| File | Ollama location |
|------|----------------|
| `distribution/compose.native-ollama.yml` | Host (`host.docker.internal:11434`) |
| `distribution/compose.docker-ollama.yml` | `ollama` Docker service; optional NVIDIA GPU via commented `deploy` block |
| `distribution/compose.no-ollama.yml` | None — cloud models only |

All three auto-load `distribution/.env` (Docker Compose convention: `.env` in same directory as compose file). Key variables: `VERDIKT_HOST_DATA_DIR` (bind-mount source on host), `VERDIKT_PORT`, `VERDIKT_JWT_SECRET`, `VERDIKT_APP_BASE_URL`, `VERDIKT_CORS_ORIGINS`. Container-internal paths (`VERDIKT_DATA_DIR=/var/lib/verdikt`) are hard-coded in the compose files.

### Setup wizard (`distribution/wizard/`)

Pure stdlib (tkinter). Entry point: `python -m wizard` from `distribution/`.

- `detect.py` — `detect_docker()`, `detect_ollama()`, `detect_nvidia_gpu()` (subprocess/urllib, no deps)
- `env_writer.py` — `validate_data_dir(path)` returns an error string if the path is non-empty (wizard blocks Next until fixed); `write_env(compose_file, port, data_dir, dist_dir)` writes `distribution/.env`, preserving an existing `VERDIKT_JWT_SECRET` on re-run
- `app.py` — `WizardApp`: 6-step tkinter window (Welcome → Prerequisites → Model Backend → Port → Data Folder → Install). Install step calls `docker compose pull` + `docker compose up -d` in a background thread, then writes `~/.verdikt_tray.json`

### Tray launcher (`distribution/tray/`)

Deps: `pystray>=0.19`, `Pillow>=10`. Entry point: `python -m tray` from `distribution/`.

- `docker_manager.py` — `DockerManager` wraps `docker compose` subprocesses: `start()`, `stop()`, `restart()`, `is_running()`, `open_logs()` (opens a terminal window per platform)
- `launcher.py` — reads `~/.verdikt_tray.json`, generates a programmatic disc icon with Pillow (`_make_icon(running: bool)`), polls `is_running()` every 10 s to update icon colour (green = running, grey = stopped)
- `autostart.py` — `register_autostart(exe)` / `unregister_autostart()`: Windows writes to `HKCU\...\Run` via `winreg`; macOS writes a LaunchAgent plist to `~/Library/LaunchAgents/com.verdikt.tray.plist`; Linux writes an XDG `.desktop` file to `~/.config/autostart/`

### Installers

- `installers/linux/install.sh` — bash; validates data dir is empty, detects Ollama, writes `distribution/.env`, installs a systemd user service for the tray
- `installers/macos/build.sh` — PyInstaller freeze + `pkgbuild` + `productbuild`; `distribution.xml` defines the installer GUI
- `installers/windows/verdikt.iss` — Inno Setup 6; bundles PyInstaller-frozen `VerdiktTray.exe` + `VerdiktWizard.exe`; checks Docker at post-install

## Domain implementation details

### Text projects
- Chunker: `TextChunker` (paragraph-aware word-count windows, configurable min/max per project)
- Embedder: `SentenceTransformerEmbedder` (bundled, no Ollama needed); Ollama embedding models selectable via catalog
- LLM: any Ollama text/any-domain model; must be set as catalog default or overridden per project
- Rating UI: renders chunk text; crystalliser uses full text content as examples in LLM prompts

### Image projects
- Chunker: `IdentityChunker` (1 image = 1 chunk, always; chunk size settings hidden in UI)
- Embedder: `CLIPEmbedder` using `openai/clip-vit-base-patch32` via HuggingFace `transformers`; not catalog-managed
- LLM: must be a vision-capable Ollama model; `LLMJudge` sends base64-encoded image bytes in Ollama's `images` field
- Rating UI: renders `<img src="data:image/jpeg;base64,...">` using `chunk_domain` flag from API
- Crystalliser: image chunks use positional label `[image #N]` in LLM prompts (no text content to quote)
- AI rater: skips text-embedding similarity ordering (CLIP cannot embed text summaries); uses random ordering instead

### Model catalog
- `auth.db` `model_catalog` table: `ModelCatalogRow` in `backend/verdikt/storage/auth_orm.py`
- Admin syncs from Ollama via `POST /api/admin/models/sync`; auto-detects type (embedding vs LLM) and domain (text/image/any) from model name and families/capabilities
- `is_default: bool` per row; at most one default per type+domain; "any"-domain conflicts are cleared on set
- `GET /api/models/defaults` → `{llm_by_domain: {text: model_id|null, image: model_id|null}}`
- `GET /api/models/domain-availability` → `{text: bool, image: bool}` — domains with no enabled LLM are disabled in project create
- `POST /api/admin/models` — manually register local models (e.g. sentence-transformer embedding models); upserts by id

## Token usage & budget

- `token_usage` and `token_grants` tables in `auth.db`; `UserRow` gains `daily_token_grant` (null=unlimited), `token_grant_expiry_days` (default 7)
- `backend/verdikt/api/token_budget.py` — `ensure_daily_grant`, `get_token_balance`, `check_token_budget` (raises 402), `record_usage`
- Daily grants are lazily issued (at first balance check of the day), not via a scheduler
- `LLMJudge._call_ollama` returns `(response, prompt_eval_count, eval_count)`; `judge.usage` accumulates per-run; flushed to auth.db by routers after each run
- `ProfileCrystalliser.crystallise` returns `(profile, total_prompt_tokens, total_completion_tokens)`
- Pre-flight `check_token_budget` before: crystallise, ai-rating/start, ai-rating/preview, ai-rating/rate-chunk
- Background ai_rating thread records accumulated usage into a fresh auth session at end of run
- `GET /api/usage` — user's balance + day/week/month/all-time + per-project breakdown
- `GET /api/admin/users/{id}/usage`, `POST /api/admin/users/{id}/grants`, `PATCH /api/admin/users/{id}/limits`

## Admin user management

- `is_founding_admin` column on `UserRow` — set True for the first registered user; cannot be demoted
- `POST /api/admin/users/{id}/promote` and `/demote` — 403 if target is founding admin or self-demote
- AdminUsers page: promote/demote buttons, grant tokens modal, daily limit + expiry settings modal

## OAuth (Google + GitHub)

- `UserRow` gains `oauth_provider`, `oauth_provider_id`, `oauth_db_key_enc`; `argon2_hash`/`kdf_salt` nullable
- OAuth users' DB key: random 32 bytes wrapped with `Fernet(HKDF(jwt_secret, "verdikt-oauth-key-wrap-v1"))`; stored in `oauth_db_key_enc`
- Stateless CSRF state: `nonce.expiry.HMAC-SHA256(jwt_secret, nonce+expiry)`, 10-minute window
- `GET /api/auth/oauth/providers` — lists configured providers
- `GET /api/auth/oauth/{provider}/authorize` → redirect to provider
- `GET /api/auth/oauth/{provider}/callback` → exchange, find/create user, issue JWT, redirect to `/`
- Find/create: look up by provider_id first, then by email (link existing), then create new
- Config: `VERDIKT_GOOGLE_CLIENT_ID`, `VERDIKT_GOOGLE_CLIENT_SECRET`, `VERDIKT_GITHUB_CLIENT_ID`, `VERDIKT_GITHUB_CLIENT_SECRET`, `VERDIKT_OAUTH_REDIRECT_BASE`
- Login page shows OAuth buttons when providers are configured; OAuth errors surfaced via `?error=` query param

## Performance notes

- **Clustering**: `MiniBatchKMeans` (batch_size=1024) instead of `KMeans`; cluster assignments written via `SQLiteChunkStore.bulk_update_clusters()` which issues a single `executemany` UPDATE instead of per-row calls.
- **Cluster sampling** (`RatingSelector._next_diversity`): uses `SQLiteChunkStore.cluster_stats()` (LEFT JOIN aggregation SQL) instead of loading all chunk metadata into Python. `random_unrated_in_cluster` uses `NOT EXISTS + ORDER BY RANDOM() LIMIT 1` in SQL.
- **Composite indexes**: `ix_chunks_project_cluster` on `(project_id, cluster_id)`; `ix_ratings_chunk_project_ai_skipped` on `(chunk_id, project_id, is_ai, skipped)`. Applied via migration in `get_user_engine` DCLP block in `deps.py`.
- **`has_profile`**: Project `GET /api/projects/{id}` response includes `has_profile: bool` (`profile is not None`). Frontend uses this instead of inferring from `profile_confidence` (which is `null` both when no profile exists and when a profile exists with zero AI confirmations).

## Venice.ai integration (Phase 1)

Venice.ai provides an OpenAI-compatible hosted LLM + embedding API (`https://api.venice.ai/api/v1`). Phase 1 lets the admin configure a site-wide API key; any user can then pick a Venice model for a project.

### LLMTarget abstraction

`backend/verdikt/inference/resolver.py` defines:

```python
@dataclass
class LLMTarget:
    provider: str       # "ollama" | "venice" | "openrouter"
    base_url: str
    model: str
    api_key: str | None = None
```

`resolve_llm_target(project, config, auth_session) -> LLMTarget` looks up the project's `llm_model` in `ModelCatalogRow`; dispatches on `source`:
- `"venice"` → reads `SiteSettingsRow("venice.api_key")`, raises `RuntimeError` if missing, returns a Venice target
- `"openrouter"` → reads `SiteSettingsRow("openrouter.api_key")`, raises `RuntimeError` if missing, returns an OpenRouter target
- `"ollama"` / anything else → reads optional `SiteSettingsRow("ollama.api_key")`, returns an Ollama target (key may be `None`)

`resolve_embedder(project, config, auth_session=None)` does the same for embedding models — when the model's catalog row has `source == "venice"` it returns `VeniceEmbedder`.

### OpenAI-compat LLM call

Venice LLM path: `POST {base_url}/chat/completions`, `Authorization: Bearer {api_key}`, body `{"model":..., "messages":[{"role":"user","content":"..."}], "response_format":{"type":"json_object"}}`. Response: `choices[0].message.content`, `usage.prompt_tokens/completion_tokens`.

Images: content becomes `[{"type":"text","text":"..."},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]`.

Three classes (`LLMJudge`, `ProfileCrystalliser`, `DimensionDiscoverer`) all accept a `target: LLMTarget` in their constructors and dispatch via `_call_llm() → _call_ollama() | _call_openai_compat()`.

### Venice embeddings

`VeniceEmbedder` (`inference/venice_embedder.py`): `POST {base_url}/embeddings`, body `{"model":"...","input":["..."]}`, response `data[].embedding` (list of float vectors). Raises `RuntimeError` on empty response, malformed shape, 401 (key invalid), or `ConnectError`.

`resolve_embedder(project, config, auth_session=None)` — the `auth_session=None` default preserves backward compatibility; when `None`, the Venice catalog check is **skipped entirely** and routing falls through to Ollama/SentenceTransformer/CLIP. Callers that may have Venice embedding models configured (pipeline, batch_ingest, ai_rating) must pass `auth_session`.

### Privacy field

`ModelCatalogRow.privacy` — synced from `model_spec.privacy` on each Venice model sync. Values:
- `"private"` — Venice does not log or retain prompts
- `"anonymized"` — Venice may retain prompts in anonymized form
- `None` — Ollama/local models (no privacy declaration)

Shown as a coloured badge in the admin model list and appended to the cost notice in `ProjectSettingsDialog`.

### DB migration

`_migrate_auth_db` in `deps.py` adds columns to existing `auth.db` installs via `ALTER TABLE`. Venice-related additions: `model_catalog.input_cost_usd_per_mtok` (REAL), `model_catalog.output_cost_usd_per_mtok` (REAL), `model_catalog.privacy` (TEXT).

### Admin endpoints

- `PUT /api/admin/venice/key` — upserts `SiteSettingsRow("venice.api_key")`
- `GET /api/admin/venice/status` → `{configured: bool, model_count: int}`
- `POST /api/admin/models/sync-venice` — fetches `GET https://api.venice.ai/api/v1/models`, classifies (embedding vs LLM), upserts `ModelCatalogRow` with `source="venice"`, disables stale Venice rows

### Frontend

`AdminModels.tsx` has a Venice section (key input + save, status line, sync button). Model list shows a purple `Venice` badge for `source === "venice"` rows. `ProjectSettingsDialog.tsx` shows a cost notice when a Venice model is selected.

No DB schema changes — `SiteSettingsRow` and `ModelCatalogRow.source` already existed.

## OpenRouter integration

OpenRouter (`https://openrouter.ai/api/v1`) provides an OpenAI-compatible gateway to hundreds of hosted models. Uses the same `_call_openai_compat()` code path as Venice. No embedding support (OpenRouter models always `source="openrouter"`, never used for embeddings).

### Admin endpoints

- `PUT /api/admin/openrouter/key` — upserts `SiteSettingsRow("openrouter.api_key")`
- `DELETE /api/admin/openrouter/key` — removes the key
- `GET /api/admin/openrouter/status` → `{configured: bool, model_count: int}`
- `POST /api/admin/models/sync-openrouter` — fetches `GET https://openrouter.ai/api/v1/models`, classifies LLM models (no embeddings), upserts `ModelCatalogRow` with `source="openrouter"`, parses pricing from `pricing.prompt`/`pricing.completion` fields

### Frontend

`AdminModels.tsx` has an OpenRouter section (key input + save/clear, status, sync button) alongside the Venice section. Model list shows a teal `OpenRouter` badge for `source === "openrouter"` rows. `ProjectSettingsDialog.tsx` shows the same cost notice as Venice when an OpenRouter model is selected.

## Ollama authentication (optional)

Ollama has no built-in auth, but admins may put it behind a reverse proxy that requires a Bearer token. The site-wide key is optional — when blank, all behaviour is identical to before.

### How it works

- Key stored as `SiteSettingsRow("ollama.api_key")` in `auth.db` (same key-value table as Venice/OpenRouter keys, no migration needed)
- `_get_ollama_key(auth_session) -> str | None` in `resolver.py` reads the row; returns `None` when absent
- `resolve_llm_target` Ollama path passes `api_key=_get_ollama_key(auth_session)` to `LLMTarget`
- `resolve_embedder` passes `api_key=_get_ollama_key(auth_session) if auth_session else None` to `OllamaEmbedder`
- All Ollama `httpx.post()` calls in `LLMJudge`, `ProfileCrystalliser`, and `DimensionDiscoverer` build `headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}` and pass it to the request
- `OllamaEmbedder.__init__` accepts `api_key: str | None = None`; `embed()` applies the same conditional header
- Catalog sync (`sync_models`): reads the key and passes `headers=extra_headers` to `ollama.Client(host=..., headers=extra_headers)` so the Python SDK also authenticates

### Admin endpoints

- `PUT /api/admin/ollama/key` — upserts `SiteSettingsRow("ollama.api_key")`
- `DELETE /api/admin/ollama/key` — removes the key
- `GET /api/admin/ollama/status` → `{configured: bool}`

### Frontend

`AdminModels.tsx` has an Ollama section at the top of the Model Catalog page (above Venice and OpenRouter) containing: optional Bearer token input with show/hide, save/clear buttons, status indicator, and the "↻ Sync from Ollama" button. A note clarifies the key is optional (standard Ollama installs need no key).

## Build order (milestones)

1. ✅ `MaterialItem` dataclass + SQLite schema + `FileDropPlugin` + chunk/embed/cluster pipeline (no UI)
2. ✅ Rating UI + storage + basic profile crystallisation via Ollama
3. ✅ `AO3Plugin` + plugin registry (`entry_points`) + auto-generated config forms
4. ✅ Embedding pre-filter + LLM judge + recommendation browser + feedback loop
5. ✅ Auth (JWT + Argon2id) + per-user SQLCipher encryption + project export/import + AI accuracy confidence + background AI preview + active learning + admin UI
6. ✅ Image domain support — CLIP embedder, vision LLM judging, identity chunker, domain-filtered plugins, per-domain model catalog with admin-managed defaults
7. ✅ Token usage tracking + budget grants, admin promote/demote, OAuth (Google/GitHub), sentence-transformer catalog
8. ✅ `ImmichPlugin` + remote content protocol + chunk descriptions from LLM judge + Immich writeback (star ratings + `#verdikt:` descriptions)
9. ✅ Discovery mode — dimension discovery from like/dislike reactions; dimension weights surfaced in UI
10. ✅ `RoyalRoadPlugin` — HTML scraping, two-stage Gaussian chapter+paragraph sampling, login/following-list support, works search box
11. ✅ Venice.ai integration (Phase 1) — admin-managed API key + model sync; `LLMTarget` abstraction; Venice LLM + embedding in all inference paths; cost notice in project settings; OpenRouter integration (same code path, no embeddings); optional Ollama Bearer-token auth forwarded to all Ollama HTTP calls and catalog sync
12. ✅ Desktop distribution — `distribution/` subdirectory: three Docker Compose variants (native Ollama / Docker Ollama / cloud-only), tkinter setup wizard with empty-dir validation and data folder picker, pystray tray launcher with green/grey status icon and start/stop/restart/logs menu, platform installers (Inno Setup 6 / pkgbuild / bash)

## Discovery mode

Helps users who struggle to define rating dimensions upfront. Flow: rate samples on a single −2/+2 preference axis with optional reason → two-stage LLM analysis → proposed dimensions for review.

- **`DiscoveryRating`** model in `core/models.py`: `preference: float` (−2 to +2), `reason: str | None`
- **`discovery_ratings`** SQLite table; new rows picked up automatically by `Base.metadata.create_all`
- **`SQLiteDiscoveryRatingStore`** in `storage/sqlite.py`: `save`, `list_by_project`, `get_rated_chunk_ids`, `counts`, `delete_by_project`
- **`DimensionDiscoverer`** in `inference/dimension_discoverer.py`: Stage 1 calls LLM per chunk to describe characteristic qualities (weighted by `|preference|`); Stage 2 synthesises proposed dimensions from liked vs. disliked quality descriptions; flags existing dims that never surfaced as `irrelevant_existing`
- **Router** `api/routers/discovery.py`, prefix `/api/projects/{id}/discovery`: `GET /next` (cluster-diversity sampling, excludes already-discovery-rated chunks), `POST /ratings`, `GET /status`, `POST /analyse/stream` (SSE), `POST /apply`, `POST /reset`
- **Ready threshold**: `liked >= 5 AND disliked >= 5` before analysis is enabled
- **Frontend**: `/projects/:id/discover` route (`DiscoveryInterface.tsx`); `DiscoveryAnalysisModal.tsx` for streaming analysis + proposal review with per-dim name/description/weight editing and irrelevant-existing keep/downweight/remove controls
- **Dimension weights** now surfaced in `DimensionEditor.tsx` (compact numeric input, highlighted when ≠ 1.0)
- Dashboard "Discover" button shows `{liked}♥ {disliked}✗` counter; turns accent-coloured when ready

## Remote content protocol

Plugins that source remote content (e.g. Immich) can store only a reference at ingest time and fetch bytes lazily:

- `MaterialItem.content_is_remote: bool = False` — signals that `content=b""` is intentional
- `PluginBase.supports_remote_content() -> bool` — classmethod; return `True` to opt in
- `PluginBase.fetch_content(source_path: str) -> bytes` — called by the pipeline chunk phase and the AI rater when `content` is empty and `content_is_remote` is set
- Three storage modes (plugin config `thumbnail_size`): `preview` (fetch once, ~200 KB), `thumbnail` (fetch once, ~30 KB), `none` (always-fetch, zero DB storage)
- For `preview`/`thumbnail`: bytes persisted to `ChunkRow.content` during pipeline; all downstream reads hit DB only
- For `none`: `ChunkRow.content` stays empty; rating router, AI rater each call `fetch_content()` on demand

## Chunk descriptions

The LLM judge (`inference/judge.py`) emits a 4th return value: a neutral factual description of the chunk (1–2 sentences, no evaluative language). Return signature: `(scores, overall, explanations, description)`. Stored in `ChunkRow.description` (nullable TEXT). Written by AI rater and live preview endpoint; surfaced as a caption in the rating interface, work detail modal, work list (first chunk's description as a collapsible one-liner), and the rated-chunks modal edit view.

In the work detail modal, each chunk block is collapsible: clicking the header (`▸`/`▾` toggle) hides the content area. The description remains visible below the header even when collapsed.

## Per-chunk AI rating

- `POST /api/projects/{id}/ai-rating/rate-chunk` — explicit user-triggered AI rating of a single chunk. Unlike `/preview`, has no `already_rated` guard: calling it on an already-rated chunk deletes the existing AI rating and saves a fresh one. Returns `{ai_rating_id, dimension_scores, explanations}`. Budgeted via `check_token_budget`.
- The work detail modal shows a `↺ AI` button in each chunk header. While the request is in flight the `↺` icon spins (CSS `@keyframes spin`). After completion the chunk list auto-refreshes via `invalidateQueries`.
- `SQLiteRatingStore.delete(rating_id)` — deletes a single rating row; used by `rate-chunk` to remove the previous AI rating before saving the new one.

## Ratings API performance

`GET /ratings/rated-chunks` is implemented as a single SQL query with `JOIN chunks JOIN material_items`, NOT EXISTS deduplication (human preferred over AI per chunk), server-side `ORDER BY` and `LIMIT/OFFSET`. Response shape: `{"total": int, "items": [...]}`. Query params: `limit`, `offset`, `sort_by` (`chunk_position` | `work_seq` | `avg_score` | `is_ai` | `dim:<name>`), `sort_dir` (`asc` | `desc`), `work_seq`. Sort column is validated against an allowlist; `dim:<name>` uses `json_extract`; direction is clamped to `ASC`/`DESC`. The `chunk_domain` field uses `c.content_is_str` to distinguish text (decode bytes to str) from image (base64-encode bytes).

`GET /ratings/counts` returns `{"human": N, "ai": N}` for the stat card on the dashboard. The dashboard uses this lightweight endpoint instead of loading all ratings. The full `GET /ratings` list is only fetched lazily inside `ProjectSettingsDialog` when the dialog opens.

## `also_ai_rated` flag

When a chunk has both a human rating and an AI rating, `get_work_chunks` and `list_rated_chunks` both return `also_ai_rated: true` on the displayed (human) rating dict. This flag lets the UI surface a dashed-border `AI` badge alongside the `Human` badge so users can see that an AI score also exists. `list_rated_chunks` deduplicates — only the best rating per chunk (human preferred over AI) is returned; the `also_ai_rated` flag on that entry signals the AI rating's existence without including a duplicate row.

## Writeback protocol

Plugins that can push data back to the source implement:

- `PluginBase.supports_writeback() -> bool` — classmethod; return `True` to opt in
- `PluginBase.writeback(project_id, session, options: dict) -> dict` — options keys: `write_ratings: bool`, `write_descriptions: bool`; returns `{"updated": N, "skipped": N, "errors": [...]}`
- `POST /api/projects/{id}/works/plugins/{name}/writeback` — calls `plugin.writeback()`; requires auth
- `GET /api/plugins` response includes `supports_writeback: bool` per plugin
- Frontend shows a **Write back** button on the project dashboard when any configured plugin has `supports_writeback=True`

## Royal Road plugin

`backend/verdikt/plugins/royalroad.py` — text-domain plugin that scrapes Royal Road (royalroad.com) via HTML; no official public API exists.

**Two-stage Gaussian sampling** (the key design difference from AO3):
1. **Chapter selection**: Gaussian weights over the ordered chapter list select which chapters to *download*. Seed: `MD5(f"ch:{fiction_id}")`. Env: `VERDIKT_RR_CHAPTER_RATE` (default `0.30`), `VERDIKT_RR_CHAPTER_STDDEV` (default `1.5`). Selection order is preserved (`np.sort`).
2. **Paragraph sampling**: Within the downloaded chapters, Gaussian weights over combined paragraphs select the final content. Seed: `MD5(f"para:{fiction_id}")`. Env: `VERDIKT_RR_SAMPLE_RATE` (default `0.20`), `VERDIKT_RR_SAMPLE_STDDEV` (default `1.5`).

This avoids fetching all chapters (saves ~70% of HTTP requests for long works) while still biasing toward middle chapters where story substance concentrates.

**Brotli encoding constraint**: The session must NOT set `Accept-Encoding: gzip, deflate, br`. Royal Road honours `br` and serves Brotli-compressed responses; `requests` cannot decompress Brotli without the optional `brotli` package (not a project dependency). Omitting the header causes `requests` to negotiate only gzip/deflate, which it handles natively.

**Rate limiting**: `VERDIKT_RR_REQUEST_DELAY` (default `2.0` s, minimum `1.0` s) applied after every HTTP request.

**Login / following list**: ASP.NET CSRF pattern — GET `/account/login` → extract `input[name="__RequestVerificationToken"]` → POST with `Email`, `Password`, `__RequestVerificationToken`. `include_following: true` in config triggers login and scrapes `/my/follows`.

**Key CSS selectors**:
- Fiction title: `h1.font-white`
- Author: `h4.font-white a`
- Chapter rows: `table#chapters tbody tr td a[href*="/chapter/"]`
- Chapter content: `div.chapter-content`
- Browse/search results: `div.fiction-list-item h2.fiction-title a`
- Last updated: last chapter row's `td time[datetime]` attribute

## Branch conventions

- **`main`** — stable, milestone-complete. Only receives merges from `develop` when a milestone ships.
- **`develop`** — integration branch. All feature work lands here; must stay runnable.
- **`feature/<milestone>-<name>`** — e.g. `feature/m1-chunker`. Branch off `develop`, merge back with a merge commit (no squash).

## AO3 plugin constraint

The AO3 plugin must respect rate limits, `robots.txt`, and AO3's terms of service. AO3 is a community resource; the plugin must not cause availability problems.
