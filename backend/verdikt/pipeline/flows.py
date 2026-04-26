from __future__ import annotations

from prefect import flow, task
from prefect.cache_policies import NO_CACHE

from verdikt.pipeline.runner import PhaseResult, PipelineResult, PipelineRunner


@task(cache_policy=NO_CACHE)
def chunk_task(runner: PipelineRunner, project_id: str) -> PhaseResult:
    return runner._chunk(project_id)


@task(cache_policy=NO_CACHE)
def embed_task(runner: PipelineRunner, project_id: str) -> PhaseResult:
    return runner._embed(project_id)


@task(cache_policy=NO_CACHE)
def cluster_task(runner: PipelineRunner, project_id: str) -> PhaseResult:
    return runner._cluster(project_id)


@flow(name="verdikt-pipeline")
def run_pipeline_flow(project_id: str, runner: PipelineRunner) -> PipelineResult:
    """Run chunk → embed → cluster as Prefect tasks.

    `runner` is passed as a plain Python arg for local synchronous execution.
    Remote Prefect workers would need to reconstruct the runner from config inside tasks.
    The caller owns the SQLAlchemy session and must commit after this flow returns.
    """
    result = PipelineResult(project_id=project_id)
    result.phases.append(chunk_task(runner, project_id))
    result.phases.append(embed_task(runner, project_id))
    result.phases.append(cluster_task(runner, project_id))
    return result
