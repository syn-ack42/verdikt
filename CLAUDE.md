# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Verdikt is a local-first, open-source **preference learning platform**. Users rate content samples across configurable dimensions; the system builds a preference model and recommends new material with per-dimension explanations. The full specification is in `verdikt_brief.md`.

## Tech stack

- **Backend**: Python, FastAPI, SQLAlchemy + SQLite (SQLCipher for per-user encryption), Prefect (pipeline orchestration)
- **Frontend**: React + TypeScript, Vite, TanStack Query
- **ML**: Ollama (local LLM), sentence-transformers (embeddings), ChromaDB (vector store)
- **Auth**: HttpOnly JWT cookie (`SameSite=Lax`), Argon2id password hashing
- **Plugin system**: Python packages registered via `entry_points`

## Architecture

Five layers with strict separation of concerns:

1. **Plugin layer** — fetches and normalises raw content into `MaterialItem` objects. Plugins know nothing about preference learning. Each plugin declares a JSON Schema config; the UI renders config forms from it automatically.
2. **Pipeline layer** — processes `MaterialItem`s through phases: `ingest → chunk → embed → cluster → rate → crystallise → evaluate → recommend`. Orchestrated by Prefect. Phases are idempotent. This layer calls storage interfaces, never SQLite directly.
3. **Storage layer** — SQLite via SQLAlchemy for structured data; ChromaDB (one collection per project) for vectors; user files encrypted at rest via `EncryptedStorageBackend` (AES-256-GCM, UUID-named blobs, manifest in per-user DB). Exposed through interfaces so the pipeline layer is decoupled from implementation.
4. **Inference layer** — Ollama for LLM tasks (profile crystallisation, LLM judging, explanations); sentence-transformers for embeddings. Abstracted so swapping providers is a config change.
5. **UI layer** — React + FastAPI. Three surfaces: project dashboard, rating interface, recommendation browser.

## Auth and per-user isolation

- **Global auth DB**: `$VERDIKT_DATA_DIR/auth.db` (default `/var/lib/verdikt/auth.db`) — plain SQLite, `users` table only (id, email, argon2 hash, salt, is_admin, is_blocked)
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

## Build order (milestones)

1. ✅ `MaterialItem` dataclass + SQLite schema + `FileDropPlugin` + chunk/embed/cluster pipeline (no UI)
2. ✅ Rating UI + storage + basic profile crystallisation via Ollama
3. ✅ `AO3Plugin` + plugin registry (`entry_points`) + auto-generated config forms
4. ✅ Embedding pre-filter + LLM judge + recommendation browser + feedback loop
5. ✅ Auth (JWT + Argon2id) + per-user SQLCipher encryption + project export/import + AI accuracy confidence + background AI preview + active learning + admin UI
6. Image domain support (CLIP) — validates domain abstraction

## Branch conventions

- **`main`** — stable, milestone-complete. Only receives merges from `develop` when a milestone ships.
- **`develop`** — integration branch. All feature work lands here; must stay runnable.
- **`feature/<milestone>-<name>`** — e.g. `feature/m1-chunker`. Branch off `develop`, merge back with a merge commit (no squash).

## AO3 plugin constraint

The AO3 plugin must respect rate limits, `robots.txt`, and AO3's terms of service. AO3 is a community resource; the plugin must not cause availability problems.
