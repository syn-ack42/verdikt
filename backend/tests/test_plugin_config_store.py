import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from verdikt.core.models import PluginConfig
from verdikt.storage.orm import Base
from verdikt.storage.sqlite import SQLitePluginConfigStore


@pytest.fixture
def store(session):
    return SQLitePluginConfigStore(session)


def test_save_and_get(store):
    cfg = PluginConfig(project_id="proj1", plugin_name="ao3", config={"username": "user", "password": "pass"})
    saved = store.save(cfg)
    retrieved = store.get("proj1", "ao3")
    assert retrieved is not None
    assert retrieved.plugin_name == "ao3"
    assert retrieved.config["username"] == "user"


def test_get_returns_none_when_absent(store):
    result = store.get("no_such_project", "ao3")
    assert result is None


def test_save_upserts(store):
    cfg1 = PluginConfig(project_id="proj1", plugin_name="ao3", config={"username": "old"})
    store.save(cfg1)
    cfg2 = PluginConfig(project_id="proj1", plugin_name="ao3", config={"username": "new"})
    store.save(cfg2)
    result = store.get("proj1", "ao3")
    assert result is not None
    assert result.config["username"] == "new"
    rows = store.list_by_project("proj1")
    assert len(rows) == 1


def test_list_by_project(store):
    store.save(PluginConfig(project_id="proj1", plugin_name="ao3", config={}))
    store.save(PluginConfig(project_id="proj2", plugin_name="ao3", config={}))
    results = store.list_by_project("proj1")
    assert len(results) == 1
    assert results[0].project_id == "proj1"


def test_delete(store):
    store.save(PluginConfig(project_id="proj1", plugin_name="ao3", config={}))
    store.delete("proj1", "ao3")
    assert store.get("proj1", "ao3") is None


def test_different_plugins_same_project(store):
    store.save(PluginConfig(project_id="proj1", plugin_name="ao3", config={"a": 1}))
    store.save(PluginConfig(project_id="proj1", plugin_name="filedrop", config={"b": 2}))
    results = store.list_by_project("proj1")
    assert len(results) == 2
    names = {r.plugin_name for r in results}
    assert names == {"ao3", "filedrop"}
