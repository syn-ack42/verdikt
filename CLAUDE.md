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
- Background AI preview fires on chunk load (normal mode, post-profile); result shown as flash bar after submit.
- Two rating modes: `normal` (rate new chunks) and `confirm_ai` (review AI-scored chunks).
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
- Pre-flight `check_token_budget` before: crystallise, ai-rating/start, ai-rating/preview
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

## Build order (milestones)

1. ✅ `MaterialItem` dataclass + SQLite schema + `FileDropPlugin` + chunk/embed/cluster pipeline (no UI)
2. ✅ Rating UI + storage + basic profile crystallisation via Ollama
3. ✅ `AO3Plugin` + plugin registry (`entry_points`) + auto-generated config forms
4. ✅ Embedding pre-filter + LLM judge + recommendation browser + feedback loop
5. ✅ Auth (JWT + Argon2id) + per-user SQLCipher encryption + project export/import + AI accuracy confidence + background AI preview + active learning + admin UI
6. ✅ Image domain support — CLIP embedder, vision LLM judging, identity chunker, domain-filtered plugins, per-domain model catalog with admin-managed defaults
7. ✅ Token usage tracking + budget grants, admin promote/demote, OAuth (Google/GitHub), sentence-transformer catalog

## Branch conventions

- **`main`** — stable, milestone-complete. Only receives merges from `develop` when a milestone ships.
- **`develop`** — integration branch. All feature work lands here; must stay runnable.
- **`feature/<milestone>-<name>`** — e.g. `feature/m1-chunker`. Branch off `develop`, merge back with a merge commit (no squash).

## AO3 plugin constraint

The AO3 plugin must respect rate limits, `robots.txt`, and AO3's terms of service. AO3 is a community resource; the plugin must not cause availability problems.
