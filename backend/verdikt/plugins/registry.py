from __future__ import annotations

from importlib.metadata import entry_points

from verdikt.plugins.base import PluginBase

_cache: dict[str, type[PluginBase]] | None = None


def load_plugins() -> dict[str, type[PluginBase]]:
    global _cache
    if _cache is None:
        eps = entry_points(group="verdikt.plugins")
        _cache = {ep.name: ep.load() for ep in eps}
    return _cache


def get_plugin(name: str) -> type[PluginBase]:
    plugins = load_plugins()
    if name not in plugins:
        raise KeyError(f"Unknown plugin: {name!r}")
    return plugins[name]
