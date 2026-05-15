"""Integration test for ProfileCrystalliser against a real Ollama instance.

Run with:
    pytest -m infra tests/test_crystalliser_infra.py -v
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from verdikt.core.config import AppConfig
from verdikt.core.models import Chunk, Domain, Project, Rating, RatingDimension
from verdikt.inference.crystalliser import ProfileCrystalliser
from verdikt.inference.resolver import LLMTarget
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteProjectStore, SQLiteRatingStore


@pytest.mark.infra
def test_crystallise_real_ollama(session: Session) -> None:
    config = AppConfig()
    proj = Project(
        name="Infra Test Project",
        domain=Domain.TEXT,
        rating_dimensions=[
            RatingDimension(name="Prose Quality", description="Clarity and style of writing", weight=1.0),
            RatingDimension(name="Pacing", description="Narrative flow and engagement", weight=1.0),
        ],
        crystallisation_threshold=2,
    )
    SQLiteProjectStore(session).create(proj)

    chunks = [
        Chunk(
            project_id=proj.id,
            material_item_id="mat1",
            content=(
                "The rain fell in silver sheets across the cobblestones, each drop "
                "catching the gaslight and shattering it into brief constellations. "
                "She walked without hurrying, her coat already soaked through, indifferent "
                "to the cold in the way only the truly exhausted can be."
            ),
            position=0, size=50, cluster_id=0,
        ),
        Chunk(
            project_id=proj.id,
            material_item_id="mat1",
            content=(
                "He went to the store. He bought milk. He came home. He drank the milk. "
                "Then he went to bed. It was Tuesday."
            ),
            position=1, size=20, cluster_id=1,
        ),
        Chunk(
            project_id=proj.id,
            material_item_id="mat2",
            content=(
                "The committee met at three. They discussed the proposal. Several members "
                "raised concerns. The vote was postponed. Everyone went home."
            ),
            position=0, size=18, cluster_id=2,
        ),
    ]
    SQLiteChunkStore(session).save_many(chunks)

    ratings = [
        Rating(
            project_id=proj.id,
            chunk_id=chunks[0].id,
            material_item_id="mat1",
            dimension_scores={"Prose Quality": 5.0, "Pacing": 4.0},
        ),
        Rating(
            project_id=proj.id,
            chunk_id=chunks[1].id,
            material_item_id="mat1",
            dimension_scores={"Prose Quality": 1.0, "Pacing": 2.0},
        ),
        Rating(
            project_id=proj.id,
            chunk_id=chunks[2].id,
            material_item_id="mat2",
            dimension_scores={"Prose Quality": 2.0, "Pacing": 1.0},
        ),
    ]
    rating_store = SQLiteRatingStore(session)
    for r in ratings:
        rating_store.save(r)
    session.commit()

    target = LLMTarget(
        provider="ollama",
        base_url=config.inference.ollama_base_url,
        model=config.inference.ollama_model,
    )
    crystalliser = ProfileCrystalliser(target)
    chunks_by_id = {c.id: c for c in chunks}
    profile, _, _ = crystalliser.crystallise(
        project=proj,
        ratings=ratings,
        chunks_by_id=chunks_by_id,
        current_version=0,
    )

    assert profile.version == 1
    assert profile.project_id == proj.id
    assert profile.rating_count == 3
    assert len(profile.dimensions) == 2

    dim_names = {d.name for d in profile.dimensions}
    assert dim_names == {"Prose Quality", "Pacing"}

    for dim in profile.dimensions:
        assert dim.summary, f"Empty summary for dimension '{dim.name}'"
        assert dim.summary != "No ratings collected for this dimension yet."
        assert 0.0 < dim.typical_score <= 5.0

    assert profile.overall_summary, "Overall summary should not be empty"
