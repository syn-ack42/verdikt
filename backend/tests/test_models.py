from verdikt.core.models import (
    Chunk,
    Domain,
    MaterialItem,
    PipelinePhase,
    Project,
    RatingDimension,
)


def test_chunk_defaults():
    c = Chunk(material_item_id="m1", project_id="p1", text="hello", position=0, word_count=1)
    assert c.id  # UUID generated
    assert c.cluster_id is None
    assert c.embedding_model is None


def test_material_item_defaults():
    item = MaterialItem(
        project_id="p1",
        source_plugin="filedrop",
        content="text",
        domain=Domain.TEXT,
        content_type="text/plain",
    )
    assert item.pipeline_phase == "ingested"
    assert item.ingested_at is not None


def test_project_defaults():
    p = Project(name="test")
    assert p.rating_dimensions == []
    assert p.created_at is not None
    assert p.chunk_min_words == 600
    assert p.chunk_max_words == 800
    assert p.crystallisation_threshold == 50


def test_pipeline_phase_values_are_strings():
    # Critical: SQLite stores these as strings
    assert PipelinePhase.INGESTED.value == "ingested"
    assert PipelinePhase.CLUSTERED.value == "clustered"


def test_rating_dimension_weight_default():
    d = RatingDimension(name="prose", description="Quality of prose")
    assert d.weight == 1.0


def test_chunk_use_enum_values():
    # use_enum_values=True means stored value is the string, not the enum
    p = Project(name="t", domain=Domain.TEXT)
    assert p.domain == "text"


def test_material_item_pipeline_phase_use_enum_values():
    item = MaterialItem(
        project_id="p1",
        source_plugin="s",
        content="x",
        domain=Domain.TEXT,
        content_type="text/plain",
    )
    assert item.pipeline_phase == "ingested"
