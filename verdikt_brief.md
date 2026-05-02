# Verdikt — Project Brief

## What is this?

Verdikt is an open-source **preference learning platform**. It helps people discover what they actually like — and why — by rating samples of content across configurable dimensions, then using those ratings to automatically evaluate and recommend new material.

The core loop is simple: show the user a representative sample → get a multi-dimensional rating → build a preference model → apply it to unseen material → recommend with explanation.

The insight driving the design: taste is tacit knowledge. People know what they like when they see it, but can't articulate it upfront. Verdikt surfaces that knowledge systematically, without requiring the user to describe their preferences in advance.

## What problem does it solve?

Discovery on content platforms (AO3, fanfiction.net, ebook stores) is broken. Recommendation algorithms optimise for engagement, not match to individual taste. Tag search is blunt. "People who liked X" assumes your taste matches a crowd. None of these tools learn *your* specific preference across multiple independent dimensions.

Verdikt fixes this by being personal, private, and multi-dimensional. Your preference model lives locally. It knows you find a certain writing style tedious even when the subject matter is compelling. It knows you'll tolerate weak prose for the right setting. Recommendations come with reasons, not just scores.

## Design principles

**Privacy first.** Preference data never leaves the user's machine unless they explicitly choose otherwise. No cloud sync by default. Each user's database is encrypted at rest with a key derived from their password (SQLCipher + Argon2id). Uploaded files are encrypted with AES-256-GCM and stored as opaque UUID blobs — a server admin with filesystem access cannot read file content or even determine what files a user has stored. This is not negotiable — it's central to the value proposition and the ethical basis for a potential monetisation model.

**Pluggable everything.** Content sources are plugins. Embedding models are plugins. The rating dimensions are configured per project. The domain (text today, images and audio tomorrow) is an abstraction, not a hardcoded assumption. New sources and new media types should drop in without touching core code.

**Project-scoped isolation.** A "project" is the unit of work. One project might be "dark fantasy fiction", another "food photography". Each has its own corpus, its own rating dimensions, its own preference profile, its own recommendation history. Projects do not share data.

**Earn the automation.** The system starts human-driven (rate this sample) and earns the right to automate (here are 20 recommendations) by accumulating enough signal. It should be honest about its confidence. Early recommendations come with low-confidence flags. This is not a system that pretends to know you from ten ratings.

**Explainability over scores.** Every recommendation includes a breakdown by dimension and a natural-language explanation from the LLM judge. A score of 4.2 is useless. "Strong match on atmosphere and prose style; subject matter is outside your typical range" is actionable.

## Architecture intent

The system has five layers. Each layer has a single responsibility and communicates with adjacent layers through well-defined interfaces.

**Plugin layer** — fetches raw material from the outside world and normalises it into MaterialItems. Plugins know nothing about preference learning. They fetch, parse, and emit. Each plugin declares its configuration schema (JSON Schema); the UI renders config forms automatically from this. Plugins are Python packages installed via entry_points — dropping in a new plugin requires no changes to core code.

**Pipeline layer** — processes MaterialItems through phases: ingest → chunk/embed/cluster → rate → crystallise → evaluate → recommend. Phases are orchestrated by Prefect. Each phase is idempotent where possible. The pipeline layer knows nothing about UI or storage implementation details.

**Storage layer** — SQLite (via SQLAlchemy) for structured data (projects, materials, chunks, ratings, profiles, recommendations). ChromaDB for vector embeddings, one collection per project. User-uploaded files stored encrypted at rest: each file is an AES-256-GCM-encrypted UUID blob with no extension or readable filename on disk; the `file_manifest` table in the per-user SQLCipher database maps UUIDs to virtual paths and metadata. Storage is an abstraction — the pipeline layer calls storage interfaces, not SQLite directly.

**Inference layer** — Ollama running locally for LLM tasks (preference profile crystallisation, LLM judging, explanation generation). sentence-transformers for embeddings. This layer is also abstracted — swapping Ollama for an API-based model should require a config change, not a code change.

**UI layer** — React frontend, FastAPI backend. The UI has three main surfaces: project dashboard (manage projects, view status), rating interface (the core human loop), recommendation browser (browse, filter, act on recommendations). The rating interface is the most important screen in the application — it will be used hundreds of times per project and must be fast, keyboard-navigable, and low-friction.

## The MaterialItem contract

Everything a plugin emits becomes a MaterialItem. This is the universal currency that flows through the entire system. It carries:
- Identity: uuid, project_id
- Provenance: source plugin, URL, work title, author, work ID, chapter position within larger work
- Content: raw bytes or string, domain (text/image/audio), content type
- Pipeline state: whether chunks and embeddings have been generated

The plugin fills provenance and content. The pipeline fills everything else. This contract must be stable — it is the interface that third-party plugin authors depend on.

## The rating loop in detail

This is the heart of the application. The user is presented with a representative chunk of source material and asked to rate it on N configurable dimensions (typically 4–6). Dimensions are defined per project with a label, description, 1–5 scale, and optional weight.

Chunk selection is intelligent:
- Early sessions: diversity sampling via clustering (maximise coverage of the material space, avoid rating three chapters from the same book)
- Later sessions: active learning / uncertainty sampling (present chunks where the current preference model is least confident — these are maximally informative)
- Always: a skip option with a reason (unrepresentative chunk, too short, etc.)

A session of 20–30 ratings should feel fast. The UI must not get in the way. Keyboard shortcuts for rating. Instant progression to the next chunk. No loading spinners between ratings.

## Profile crystallisation

After sufficient ratings (configurable threshold, suggested minimum ~50), the system crystallises a preference profile. This is a structured JSON document that describes the user's taste across dimensions, derived by an LLM from the rated corpus — weighted by scores. The user reviews and can edit this profile. It becomes the system prompt for the LLM judge.

The profile is human-readable by design. If a user can't recognise themselves in it, it's wrong and they should be able to fix it. It is also versionable — profiles can be snapshotted so the user can see how their taste has evolved.

## Recommendation engine

New candidate material goes through two stages:
1. Embedding similarity pre-filter: cheap, fast, drops obvious mismatches
2. LLM judge: scores surviving candidates per dimension against the preference profile, returns structured scores + natural language explanation

Output is a ranked list with per-dimension breakdown and explanation. The user can act on recommendations (mark as read, rate it properly to reinforce the model, link out to source).

## Monetisation and ethics

Verdikt has the innate ability to refer users to vendor sites (Amazon, etc.) for material it has recommended. A service hosting Verdikt can do this in a uniquely ethical and strictly private way. The ethical basis: it only refers people to things they have said, through their own ratings, that they would likely enjoy. It does not sell preference data. It does not reveal taste profiles to vendors. The referral is a pointer to a thing the user wants — the vendor learns only that someone clicked a link, not why.

Preference data stays local and can be encrypted. This is the explicit trade: A Verdikt service can earn referral revenue because users trust that their data is private. Violating that trust destroys the product.

## Domain extensibility

The platform is built text-first but must not be text-only in its architecture. The chunker, embedder, and rating UI display are domain-specific components behind interfaces. An image project uses CLIP embeddings and displays images in the rating UI. An audio project uses a music embedding model and plays clips. Everything from clustering onward is domain-agnostic because it operates on embedding vectors and rating scalars.

This extensibility is a design constraint from day one, not a future refactor.

## Build order and milestones

**Milestone 1 — Core plumbing**
MaterialItem dataclass and SQLite schema. FileDropPlugin. Phase 1 pipeline (chunk, embed, cluster). No UI yet — CLI or notebook to verify.

**Milestone 2 — The loop works**
Rating UI (React). Rating storage. Basic profile crystallisation via Ollama. A human can go from file dump → rate samples → see a preference profile.

**Milestone 3 — Plugin architecture proven**
AO3Plugin implemented. Plugin registry and entry_points system. Config schema → auto-generated UI forms. A third-party developer could write a plugin by reading the interface alone.

**Milestone 4 — Recommendations**
Embedding pre-filter. LLM judge with profile. Recommendation browser UI. Feedback loop (rating a recommendation reinforces the model).

**Milestone 5 — Production hardening** *(complete)*
User authentication (email/password, HttpOnly JWT cookie). Per-user data isolation with SQLCipher-encrypted databases. AES-256-GCM file encryption at rest (opaque UUID blobs, metadata in encrypted DB). Project export/import. AI-accuracy-based confidence indicators. Background AI preview in rating interface. Active learning for chunk selection. Admin user management UI. Docker deployment (multi-stage image, docker-compose, static frontend served by uvicorn).

**Milestone 6 — Domain extensibility** *(complete)*
Image domain support (CLIP embeddings, image display in rating UI). Validates that the domain abstraction actually works.

**Milestone 7 — Token budget, OAuth, sentence-transformer catalog** *(complete)*
Token usage tracking with per-user daily grant budgets and admin controls. Admin promote/demote and user blocking. Google and GitHub OAuth login. Sentence-transformer embedding models added to the model catalog (manually registered, not Ollama-synced).

**Milestone 8 — Immich, remote content, chunk descriptions, writeback** *(complete)*
`ImmichPlugin` — sources photos from a self-hosted Immich instance by album, search query, or entire library. Remote content protocol — plugins can store only a reference at ingest; bytes are fetched lazily on pipeline execution (three modes: `preview`, `thumbnail`, `none`). Chunk descriptions — the LLM judge emits a neutral 1–2 sentence factual description of each chunk alongside scores; stored on `ChunkRow`, surfaced throughout the UI. Immich writeback — user-triggered: writes Verdikt star ratings and/or generated descriptions back to Immich assets. Config form improvements: `enum` fields render as dropdowns; object-array fields with `(for type=X)` descriptions are shown/hidden based on a discriminator field in the same row.

**Post-M8 UX improvements**
Per-chunk AI rating in work detail — a `↺ AI` button on each chunk block lets users trigger or re-trigger AI rating for a single chunk without running a full batch. Human-rated chunks that also have a stored AI rating show a dashed-border `AI` badge so the dual-rating state is visible. The rated-chunks list deduplicates: one entry per chunk, human preferred over AI, with an `also_ai_rated` flag. Chunk blocks in work detail are collapsible (click header to toggle); the AI-generated description remains visible even when collapsed. "Chunk N of M" label is suppressed when a work has only one chunk.

## What this is not

Verdikt is not a social recommendation system. There is no "users who liked X also liked Y". Taste is personal and the system treats it that way.

Verdikt is not a scraping tool. Plugins that fetch from external sites must respect rate limits, robots.txt, and terms of service. The AO3 plugin in particular must be polite — AO3 is a community resource and the Verdikt community should not be the reason it goes down.

Verdikt is not an AI that tells you what you should like. It learns what you do like and finds more of it. The user's ratings are ground truth. The system has no opinion about whether your taste is good.

