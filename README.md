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

```bash
# Create a project
verdikt project create "dark-fantasy" --description "Dark fantasy fiction"

# Ingest local files (.txt, .epub, .pdf, .html, .md)
verdikt ingest dark-fantasy ./my-books/

# Run the pipeline (chunk → embed → cluster)
verdikt pipeline run dark-fantasy
```

## Running tests

```bash
cd backend

# Unit tests only (no infrastructure required)
pytest

# Include tests that require Ollama + ChromaDB
pytest -m infra
```

## Project structure

```
backend/          Python package — pipeline, storage, plugins, inference, CLI
frontend/         React + TypeScript UI (Milestone 2+)
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
