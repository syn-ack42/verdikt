from __future__ import annotations

import click
import chromadb
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.config import AppConfig
from verdikt.core.models import Domain, Project
from verdikt.inference.embedder import SentenceTransformerEmbedder
from verdikt.pipeline.chunker import TextChunker
from verdikt.pipeline.runner import PipelineRunner
from verdikt.plugins.filedrop import FileDropPlugin
from verdikt.storage.chroma import ChromaVectorStore
from verdikt.storage.orm import Base
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore


def _make_engine(config: AppConfig):
    config.ensure_dirs()
    engine = create_engine(f"sqlite:///{config.db_path}")
    Base.metadata.create_all(engine)
    return engine


@click.group()
def app() -> None:
    """Verdikt — local-first preference learning."""


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
        store = SQLiteProjectStore(session)
        store.create(proj)
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


@app.command()
@click.argument("project_id")
@click.argument("path")
def ingest(project_id: str, path: str) -> None:
    """Ingest files from PATH into PROJECT_ID."""
    config = AppConfig()
    engine = _make_engine(config)
    with Session(engine) as session:
        if SQLiteProjectStore(session).get(project_id) is None:
            click.echo(f"Project '{project_id}' not found.", err=True)
            raise SystemExit(1)
        store = SQLiteMaterialStore(session)
        count = 0
        for item in FileDropPlugin(path).fetch(project_id):
            store.save(item)
            count += 1
        session.commit()
    click.echo(f"Ingested {count} item(s) into {project_id}.")


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
        proj = SQLiteProjectStore(session).get(project_id)
        if proj is None:
            click.echo(f"Project '{project_id}' not found.", err=True)
            raise SystemExit(1)

        click.echo("Loading embedding model...")
        runner = PipelineRunner(
            material_store=SQLiteMaterialStore(session),
            chunk_store=SQLiteChunkStore(session),
            vector_store=ChromaVectorStore(
                chromadb.PersistentClient(path=str(config.chroma_path)),
                f"project_{project_id}",
            ),
            embedder=SentenceTransformerEmbedder(),
            chunker=TextChunker(
                min_words=proj.chunk_min_words,
                max_words=proj.chunk_max_words,
            ),
        )
        result = runner.run(project_id)
        session.commit()

    for phase in result.phases:
        click.echo(f"  {phase.phase}: {phase.items_processed} processed")
    click.echo(f"Done. Total items processed: {result.total_processed}")
