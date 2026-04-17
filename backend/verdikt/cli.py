import click


@click.group()
def app() -> None:
    """Verdikt — local-first preference learning."""


@app.group()
def project() -> None:
    """Manage projects."""


@project.command("create")
@click.argument("name")
@click.option("--description", "-d", default=None, help="Optional description.")
def project_create(name: str, description: str | None) -> None:
    """Create a new project named NAME."""
    raise NotImplementedError


@project.command("list")
def project_list() -> None:
    """List all projects."""
    raise NotImplementedError


@app.command()
@click.argument("project_id")
@click.argument("path")
def ingest(project_id: str, path: str) -> None:
    """Ingest files from PATH into PROJECT_ID."""
    raise NotImplementedError


@app.group()
def pipeline() -> None:
    """Pipeline commands."""


@pipeline.command("run")
@click.argument("project_id")
def pipeline_run(project_id: str) -> None:
    """Run the full pipeline (chunk → embed → cluster) for PROJECT_ID."""
    raise NotImplementedError
