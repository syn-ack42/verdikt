from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import click
import chromadb
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.config import AppConfig
from verdikt.core.models import Domain, MaterialItem, PipelinePhase, Project
from verdikt.inference.embedder import SentenceTransformerEmbedder
from verdikt.pipeline.chunker import TextChunker
from verdikt.pipeline.flows import run_pipeline_flow
from verdikt.pipeline.runner import PipelineRunner
from verdikt.plugins.filedrop import FileDropPlugin, _EXT_TO_CONTENT_TYPE
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.orm import Base
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore


def _make_engine(config: AppConfig):
    config.ensure_dirs()
    engine = create_engine(f"sqlite:///{config.db_path}")
    Base.metadata.create_all(engine)
    return engine


def _resolve_project(session: Session, id_or_name: str):
    """Resolve a project by ID or name. Errors on ambiguous name."""
    store = SQLiteProjectStore(session)
    proj = store.get(id_or_name)
    if proj is not None:
        return proj
    matches = store.get_by_name(id_or_name)
    if not matches:
        click.echo(f"Project '{id_or_name}' not found.", err=True)
        raise SystemExit(1)
    if len(matches) > 1:
        click.echo(
            f"Multiple projects named '{id_or_name}' — use the project ID instead.",
            err=True,
        )
        raise SystemExit(1)
    return matches[0]


def _resolve_work(session: Session, project_id: str, ref: str):
    """Resolve a work by project-local sequence number or full source path."""
    mat_store = SQLiteMaterialStore(session)
    if ref.isdigit():
        item = mat_store.get_by_seq(project_id, int(ref))
    else:
        item = mat_store.get_by_source_path(project_id, ref)
    return item


def _make_vector_store(config: AppConfig, project_id: str) -> ChromaVectorStore:
    return ChromaVectorStore(
        chromadb.PersistentClient(path=str(config.chroma_path)),
        f"project_{project_id}",
    )


def _make_runner(session: Session, config: AppConfig, proj) -> PipelineRunner:
    return PipelineRunner(
        material_store=SQLiteMaterialStore(session),
        chunk_store=SQLiteChunkStore(session),
        vector_store=_make_vector_store(config, proj.id),
        embedder=SentenceTransformerEmbedder(),
        chunker=TextChunker(min_words=proj.chunk_min_size, max_words=proj.chunk_max_size),
    )


def _delete_work_data(
    session: Session,
    config: AppConfig,
    project_id: str,
    item_id: str,
) -> int:
    """Delete chunks + vectors for a material item. Returns chunk count deleted."""
    chunk_store = SQLiteChunkStore(session)
    chunks = chunk_store.list_by_material(item_id)
    chunk_ids = [c.id for c in chunks]
    _make_vector_store(config, project_id).delete_items(chunk_ids)
    chunk_store.delete_by_material(item_id)
    return len(chunk_ids)


# ── app ──────────────────────────────────────────────────────────────────────

@click.group()
def app() -> None:
    """Verdikt — local-first preference learning."""


# ── project ──────────────────────────────────────────────────────────────────

@app.group()
def project() -> None:
    """Manage projects."""


@project.command("create")
@click.argument("name")
@click.option("--description", "-d", default=None, help="Optional description.")
@click.option(
    "--domain",
    type=click.Choice(["text", "image", "audio"]),
    default="text",
    show_default=True,
)
def project_create(name: str, description: str | None, domain: str) -> None:
    """Create a new project named NAME."""
    config = AppConfig()
    engine = _make_engine(config)
    proj = Project(name=name, description=description, domain=Domain(domain))
    with Session(engine) as session:
        SQLiteProjectStore(session).create(proj)
        session.commit()
    click.echo(f"Created project  {proj.id}  {proj.name}")


@project.command("list")
def project_list() -> None:
    """List all projects."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        projects = SQLiteProjectStore(session).list_all()
    if not projects:
        click.echo("No projects found.")
        return
    for p in projects:
        click.echo(f"{p.id}  {p.name}  [{p.domain}]  {p.created_at:%Y-%m-%d}")


@project.command("show")
@click.argument("project_id")
def project_show(project_id: str) -> None:
    """Show details and statistics for a project (ID or name)."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        items = SQLiteMaterialStore(session).list_by_project(proj.id)
        chunk_count = len(SQLiteChunkStore(session).list_by_project(proj.id))

    phase_counts: dict[str, int] = {}
    for item in items:
        phase_counts[item.pipeline_phase] = phase_counts.get(item.pipeline_phase, 0) + 1

    click.echo(f"ID:          {proj.id}")
    click.echo(f"Name:        {proj.name}")
    click.echo(f"Description: {proj.description or '—'}")
    click.echo(f"Domain:      {proj.domain}")
    click.echo(f"Created:     {proj.created_at:%Y-%m-%d %H:%M}")
    click.echo(f"Chunk size:  {proj.chunk_min_size}–{proj.chunk_max_size} (domain units)")
    click.echo(f"Crystallise: {proj.crystallisation_threshold} ratings")
    if proj.rating_dimensions:
        dims = ", ".join(f"{d.name} (×{d.weight})" for d in proj.rating_dimensions)
        click.echo(f"Dimensions:  {dims}")
    click.echo(f"Works:       {len(items)}")
    click.echo(f"Chunks:      {chunk_count}")
    if phase_counts:
        phases = "  ".join(f"{ph}:{n}" for ph, n in sorted(phase_counts.items()))
        click.echo(f"Phases:      {phases}")


@project.command("works")
@click.argument("project_id")
@click.option("--phase", default=None, help="Filter by pipeline phase.")
def project_works(project_id: str, phase: str | None) -> None:
    """List works in a project (ID or name)."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        phase_filter = PipelinePhase(phase) if phase else None
        items = SQLiteMaterialStore(session).list_by_project(proj.id, phase=phase_filter)

    if not items:
        click.echo("No works found.")
        return
    for item in items:
        fingerprint = item.content_hash[:12] if item.content_hash else "—" * 12
        seq = f"#{item.project_seq}" if item.project_seq is not None else "  —"
        click.echo(
            f"{seq:<5}  {item.pipeline_phase:<12}  {fingerprint}  "
            f"{item.ingested_at:%Y-%m-%d}  "
            f"{Path(item.source_path).name if item.source_path else (item.work_title or item.id)}"
        )


@project.command("delete")
@click.argument("project_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def project_delete(project_id: str, yes: bool) -> None:
    """Delete a project and all its works, chunks, and vectors."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        if not yes:
            click.confirm(
                f"Permanently delete project '{proj.name}' and all its data?",
                abort=True,
            )
        mat_store = SQLiteMaterialStore(session)
        items = mat_store.list_by_project(proj.id)
        for item in items:
            _delete_work_data(session, config, proj.id, item.id)
            mat_store.delete(item.id)
        _make_vector_store(config, proj.id).delete_collection()
        SQLiteProjectStore(session).delete(proj.id)
        session.commit()
    click.echo(f"Deleted project '{proj.name}' ({len(items)} work(s) removed).")


# ── work ─────────────────────────────────────────────────────────────────────

@app.group()
def work() -> None:
    """Inspect individual works."""


@work.command("show")
@click.argument("project_id")
@click.argument("work_ref")
def work_show(project_id: str, work_ref: str) -> None:
    """Show details for a work. WORK_REF is a sequence number (#1, 1) or source path."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        item = _resolve_work(session, proj.id, work_ref)
        if item is None:
            click.echo(f"Work '{work_ref}' not found.", err=True)
            raise SystemExit(1)
        chunks = SQLiteChunkStore(session).list_by_material(item.id)

    cluster_ids = sorted({c.cluster_id for c in chunks if c.cluster_id is not None})
    click.echo(f"ID:           {item.id}")
    click.echo(f"Seq:          #{item.project_seq}")
    click.echo(f"Source path:  {item.source_path or '—'}")
    click.echo(f"Title:        {item.work_title or '—'}")
    click.echo(f"Author:       {item.author or '—'}")
    click.echo(f"URL:          {item.url or '—'}")
    click.echo(f"Domain:       {item.domain}")
    click.echo(f"Content type: {item.content_type}")
    click.echo(f"Phase:        {item.pipeline_phase}")
    click.echo(f"Ingested:     {item.ingested_at:%Y-%m-%d %H:%M}")
    click.echo(f"Hash:         {item.content_hash or '—'}")
    click.echo(f"Chunks:       {len(chunks)}")
    if cluster_ids:
        click.echo(f"Clusters:     {cluster_ids}")


# ── ingest / add / remove ────────────────────────────────────────────────────

@app.command()
@click.argument("project_id")
@click.argument("path")
def ingest(project_id: str, path: str) -> None:
    """Ingest files from PATH into a project (ID or name), recursive."""
    ingest_path = Path(path).resolve()
    if not ingest_path.is_dir():
        click.echo(f"Directory not found: {ingest_path}", err=True)
        raise SystemExit(1)
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        store = SQLiteMaterialStore(session)
        added = updated = skipped = 0
        for item in FileDropPlugin(str(ingest_path)).fetch(proj.id):
            existing = (
                store.get_by_source(proj.id, item.source_plugin, item.source_path)
                if item.source_path else None
            )
            if existing is None:
                store.save(item)
                added += 1
            elif existing.content_hash != item.content_hash:
                store.update_content(existing.id, item.content, item.content_hash)
                updated += 1
            else:
                skipped += 1
        session.commit()
    click.echo(f"Ingest complete — added: {added}, updated: {updated}, unchanged: {skipped}.")


@app.command()
@click.argument("project_id")
@click.argument("file_path")
def add(project_id: str, file_path: str) -> None:
    """Add or update a single FILE_PATH in PROJECT_ID.

    Uses the absolute file path as the identity key, consistent with ingest.
    """
    config = AppConfig()
    engine = _make_engine(config)
    fp = Path(file_path).resolve()

    if not fp.is_file():
        click.echo(f"File not found: {fp}", err=True)
        raise SystemExit(1)

    ext = fp.suffix.lower()
    if ext not in FileDropPlugin.SUPPORTED_EXTENSIONS:
        click.echo(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(FileDropPlugin.SUPPORTED_EXTENSIONS))}",
            err=True,
        )
        raise SystemExit(1)

    try:
        text = FileDropPlugin._extract_text(fp)
    except Exception as exc:
        click.echo(f"Failed to parse {fp.name}: {exc}", err=True)
        raise SystemExit(1)

    if not text or not text.strip():
        click.echo("File is empty after parsing — nothing to add.", err=True)
        raise SystemExit(1)

    raw_bytes = text.encode("utf-8") if isinstance(text, str) else text
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    source_path = str(fp)

    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        mat_store = SQLiteMaterialStore(session)
        existing = mat_store.get_by_source_path(proj.id, source_path)

        if existing is None:
            item = MaterialItem(
                project_id=proj.id,
                source_plugin=FileDropPlugin.plugin_name,
                source_path=source_path,
                content_hash=content_hash,
                url=fp.as_uri(),
                work_title=fp.stem,
                content=text,
                domain=Domain.TEXT,
                content_type=_EXT_TO_CONTENT_TYPE[ext],
            )
            mat_store.save(item)
            session.commit()
            click.echo(f"Added '{fp.name}'.")
        elif existing.content_hash != content_hash:
            mat_store.update_content(existing.id, text, content_hash)
            session.commit()
            click.echo(f"Updated '{fp.name}'.")
        else:
            click.echo(f"'{fp.name}' is unchanged — nothing to do.")


@app.command()
@click.argument("project_id")
@click.argument("work_ref")
def remove(project_id: str, work_ref: str) -> None:
    """Remove a work (and its chunks/vectors) from PROJECT_ID.

    WORK_REF is a sequence number (1) or source path. PROJECT_ID can be an ID or name.
    """
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        mat_store = SQLiteMaterialStore(session)
        item = _resolve_work(session, proj.id, work_ref)
        if item is None:
            click.echo(f"Work '{work_ref}' not found.", err=True)
            raise SystemExit(1)

        label = item.source_path or item.work_title or item.id
        n_chunks = _delete_work_data(session, config, proj.id, item.id)
        mat_store.delete(item.id)
        session.commit()

    click.echo(f"Removed '{label}' ({n_chunks} chunk(s) deleted).")


# ── serve ─────────────────────────────────────────────────────────────────────

@app.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True)
@click.option("--reload", is_flag=True, help="Enable auto-reload (development).")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the Verdikt API server."""
    import uvicorn
    uvicorn.run("verdikt.api.app:app", host=host, port=port, reload=reload)


# ── pipeline ──────────────────────────────────────────────────────────────────

@app.group()
def pipeline() -> None:
    """Pipeline commands."""


@pipeline.command("run")
@click.argument("project_id")
def pipeline_run(project_id: str) -> None:
    """Run the full pipeline (chunk → embed → cluster) for PROJECT_ID."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        click.echo("Loading embedding model...")
        runner = _make_runner(session, config, proj)
        result = run_pipeline_flow(project_id=proj.id, runner=runner)
        session.commit()

    if result.total_processed == 0:
        click.echo("Nothing to do — all works are already fully processed.")
    else:
        for phase in result.phases:
            if phase.items_processed > 0:
                click.echo(f"  {phase.phase}: {phase.items_processed} processed")
        click.echo(f"Done. Total items processed: {result.total_processed}")


@pipeline.command("run-work")
@click.argument("project_id")
@click.argument("work_ref")
def pipeline_run_work(project_id: str, work_ref: str) -> None:
    """Re-run the pipeline for a single work.

    WORK_REF is a sequence number (1) or source path. PROJECT_ID can be an ID or name.
    Deletes existing chunks and vectors, resets to INGESTED, then runs
    chunk → embed → cluster for the whole project (cluster labels are project-wide).
    """
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        proj = _resolve_project(session, project_id)
        mat_store = SQLiteMaterialStore(session)
        item = _resolve_work(session, proj.id, work_ref)
        if item is None:
            click.echo(f"Work '{work_ref}' not found.", err=True)
            raise SystemExit(1)

        label = item.source_path or item.work_title or item.id
        n_chunks = _delete_work_data(session, config, proj.id, item.id)
        mat_store.update_phase(item.id, PipelinePhase.INGESTED)
        click.echo(f"Reset '{label}' ({n_chunks} old chunk(s) removed). Loading embedding model...")

        runner = _make_runner(session, config, proj)
        result = run_pipeline_flow(project_id=proj.id, runner=runner)
        session.commit()

    for phase in result.phases:
        click.echo(f"  {phase.phase}: {phase.items_processed} processed")
    click.echo("Done.")
