from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from verdikt.api.deps import get_current_user
from verdikt.core.user_models import AuthenticatedUser
from verdikt.plugins.registry import load_plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
def list_plugins(_: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> list[dict]:
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
