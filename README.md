# Verdikt

A local-first, open-source preference learning platform. Rate content samples across configurable dimensions, build a personal preference model, and receive recommendations with per-dimension explanations — entirely on your machine.

## How it works

1. **Ingest** — point Verdikt at local files or connect a content source plugin
2. **Rate** — score representative chunks on dimensions you define (prose quality, atmosphere, pacing, etc.)
3. **Crystallise** — after ~50 ratings, the system derives a structured preference profile via a local LLM
4. **Recommend** — new material is scored against your profile; every recommendation includes a breakdown by dimension

## Requirements

- Python 3.11+
- Node 18+ (frontend, Milestone 2+)
- [Ollama](https://ollama.com) with `llama3.1:8b` pulled

```bash
ollama pull llama3.1:8b
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e backend/
```

## CLI (Milestone 1)

### Projects

All commands accept either the project UUID or its name. If two projects share a name, use the UUID.

```bash
# Create a project
verdikt project create "dark-fantasy" --description "Dark fantasy fiction" --domain text

# List all projects
verdikt project list

# Show project details (work count, chunk count, phase breakdown, settings)
verdikt project show "dark-fantasy"

# List works — each work has a project-local sequence number (#1, #2, ...)
verdikt project works "dark-fantasy"
verdikt project works "dark-fantasy" --phase clustered   # filter by pipeline phase

# Delete a project and all its data (prompts for confirmation)
verdikt project delete "dark-fantasy"
verdikt project delete "dark-fantasy" --yes              # skip prompt
```

### Ingesting content

Supported formats: `.txt`, `.md`, `.html`, `.epub`, `.pdf`

```bash
# Ingest a directory (recursive). Re-running is safe: new files are added,
# changed files are updated, unchanged files are skipped.
verdikt ingest <project_id> ./my-books/

# Add or update a single file
verdikt add <project_id> /path/to/book.epub
```

Both commands identify files by their absolute path, so `ingest` and `add`
use the same identity key and are fully interchangeable for a given file.

### Inspecting works

`project works` lists each work with its sequence number and filename. Use the sequence number or full path as `WORK_REF` in any work command.

```bash
# Show full details for a work (phase, absolute path, hash, chunk count, cluster IDs)
verdikt work show "dark-fantasy" 1          # by sequence number
verdikt work show "dark-fantasy" /abs/path/to/book.epub   # by full path
```

### Running the pipeline

```bash
# Run chunk → embed → cluster for all pending works
verdikt pipeline run "dark-fantasy"

# Re-process a single work (resets to INGESTED, re-runs full pipeline;
# cluster labels are re-computed project-wide)
verdikt pipeline run-work "dark-fantasy" 2
verdikt pipeline run-work "dark-fantasy" /abs/path/to/book.epub
```

### Removing content

```bash
# Remove a work and all its chunks and vectors (sequence number or full path)
verdikt remove "dark-fantasy" 3
verdikt remove "dark-fantasy" /abs/path/to/book.epub
```

### Typical workflow

```bash
verdikt project create "my-library" --description "Fiction collection"
verdikt ingest "my-library" ~/books/fiction/
verdikt pipeline run "my-library"

# Later: add a new book and re-run
verdikt add "my-library" ~/books/fiction/new-book.epub
verdikt pipeline run "my-library"

# Re-process a specific work by sequence number
verdikt pipeline run-work "my-library" 5
```

### Resetting the data directory

All data lives in `~/.verdikt`. To start fresh:

```bash
rm -rf ~/.verdikt
```

The directory and schema are recreated automatically on next use.

## Running tests

```bash
cd backend

# Unit tests only (no infrastructure required)
pytest -m "not infra"

# Full suite (requires sentence-transformers model download + ChromaDB)
pytest
```

## Project structure

```
backend/          Python package — pipeline, storage, plugins, inference, CLI
frontend/         React + TypeScript UI (Milestone 2+)
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
