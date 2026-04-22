from __future__ import annotations

from fastapi import APIRouter

from verdikt.plugins.registry import load_plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
def list_plugins() -> list[dict]:
    plugins = load_plugins()
    result = []
    for name, cls in plugins.items():
        schema = cls.config_schema()
        result.append({
            "name": name,
            "title": schema.get("title", name),
            "description": schema.get("description", ""),
            "config_schema": schema,
        })
    return result
