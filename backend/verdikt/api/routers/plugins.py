from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from verdikt.api.deps import get_current_user
from verdikt.core.user_models import AuthenticatedUser
from verdikt.plugins.registry import load_plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
def list_plugins(
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
    domain: str | None = None,
) -> list[dict]:
    from verdikt.core.models import Domain
    plugins = load_plugins()
    result = []
    for name, cls in plugins.items():
        if domain is not None:
            try:
                d = Domain(domain)
            except ValueError:
                d = None
            if d is not None and d not in cls.supported_domains:
                continue
        schema = cls.config_schema()
        result.append({
            "name": name,
            "title": schema.get("title", name),
            "description": schema.get("description", ""),
            "config_schema": schema,
        })
    return result


@router.get("/{plugin_name}/help")
def plugin_help(
    plugin_name: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict:
    plugins = load_plugins()
    if plugin_name not in plugins:
        raise HTTPException(status_code=404, detail="Plugin not found")
    markdown = plugins[plugin_name].help_markdown()
    return {"markdown": markdown}
