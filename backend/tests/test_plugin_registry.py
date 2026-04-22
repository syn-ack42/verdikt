from verdikt.plugins.storage import StoragePlugin
from verdikt.plugins.registry import get_plugin, load_plugins


def test_load_plugins_contains_storage():
    plugins = load_plugins()
    assert "storage" in plugins


def test_load_plugins_contains_ao3():
    plugins = load_plugins()
    assert "ao3" in plugins


def test_get_plugin_storage():
    assert get_plugin("storage") is StoragePlugin


def test_get_plugin_unknown_raises():
    try:
        get_plugin("nonexistent_plugin_xyz")
        assert False, "Expected KeyError"
    except KeyError:
        pass


def test_load_plugins_returns_classes():
    plugins = load_plugins()
    for name, cls in plugins.items():
        assert hasattr(cls, "config_schema")
        assert hasattr(cls, "fetch")
        assert hasattr(cls, "plugin_name")
