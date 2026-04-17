# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Verdikt is a local-first, open-source **preference learning platform**. Users rate content samples across configurable dimensions; the system builds a preference model and recommends new material with per-dimension explanations. The full specification is in `verdikt_brief.md`.

## Planned tech stack

- **Backend**: Python, FastAPI, SQLAlchemy + SQLite, Prefect (pipeline orchestration)
- **Frontend**: React
- **ML**: Ollama (local LLM), sentence-transformers (embeddings), ChromaDB (vector store)
- **Plugin system**: Python packages registered via `entry_points`

## Architecture

Five layers with strict separation of concerns:

1. **Plugin layer** — fetches and normalises raw content into `MaterialItem` objects. Plugins know nothing about preference learning. Each plugin declares a JSON Schema config; the UI renders config forms from it automatically.
2. **Pipeline layer** — processes `MaterialItem`s through phases: `ingest → chunk → embed → cluster → rate → crystallise → evaluate → recommend`. Orchestrated by Prefect. Phases are idempotent. This layer calls storage interfaces, never SQLite directly.
3. **Storage layer** — SQLite via SQLAlchemy for structured data; ChromaDB (one collection per project) for vectors; raw files on disk. Exposed through interfaces so the pipeline layer is decoupled from implementation.
4. **Inference layer** — Ollama for LLM tasks (profile crystallisation, LLM judging, explanations); sentence-transformers for embeddings. Abstracted so swapping providers is a config change.
5. **UI layer** — React + FastAPI. Three surfaces: project dashboard, rating interface, recommendation browser.

## The MaterialItem contract

`MaterialItem` is the universal data structure crossing all layer boundaries. It is the interface third-party plugin authors depend on — treat it as a stable public API.

Fields:
- **Identity**: `uuid`, `project_id`
- **Provenance**: source plugin, URL, work title, author, work ID, chapter position
- **Content**: raw bytes or string, `domain` (`text`/`image`/`audio`), content type
- **Pipeline state**: whether chunks and embeddings have been generated

The plugin fills provenance and content. The pipeline fills everything else.

## Key design constraints

**Privacy is non-negotiable.** Preference data never leaves the machine by default. Profile encryption must be supported. This is the ethical basis for a potential monetisation model — violating it destroys the product.

**Domain abstraction from day one.** The chunker, embedder, and rating UI display are domain-specific components behind interfaces. Everything from clustering onward is domain-agnostic (operates on embedding vectors and rating scalars). Do not hardcode text-only assumptions even though the initial implementation is text-first.

**Pluggable everything.** New content sources, embedding models, and rating dimensions must drop in without touching core code.

**Project-scoped isolation.** Projects never share corpus, ratings, profiles, or recommendation history.

## Rating loop specifics

- Early sessions use diversity sampling (cluster-based) to maximise corpus coverage.
- Later sessions use uncertainty sampling (active learning) to target maximally informative chunks.
- A session of 20–30 ratings must feel fast: keyboard shortcuts, instant progression, no spinners between ratings. The rating interface is the most-used screen in the application.

## Recommendation engine

Two-stage: embedding similarity pre-filter (cheap) → LLM judge scoring surviving candidates per dimension against the preference profile (returns structured scores + natural language explanation). Output is always a ranked list with per-dimension breakdown, not bare scores.

## Build order (milestones)

1. `MaterialItem` dataclass + SQLite schema + `FileDropPlugin` + chunk/embed/cluster pipeline (no UI)
2. Rating UI + storage + basic profile crystallisation via Ollama
3. `AO3Plugin` + plugin registry (`entry_points`) + auto-generated config forms
4. Embedding pre-filter + LLM judge + recommendation browser + feedback loop
5. Profile encryption + project export/import + confidence indicators + active learning + large corpus performance
6. Image domain support (CLIP) — validates domain abstraction

## AO3 plugin constraint

The AO3 plugin must respect rate limits, `robots.txt`, and AO3's terms of service. AO3 is a community resource; the plugin must not cause availability problems.
