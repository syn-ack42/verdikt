from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from verdikt.api.deps import get_current_user, get_session
from verdikt.core.user_models import AuthenticatedUser
from verdikt.plugins.registry import load_plugins, get_plugin
from verdikt.storage.sqlite import SQLitePluginConfigStore

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
            "actions": cls.plugin_actions(),
            "supports_batched_ingest": cls.supports_batched_ingest(),
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


@router.post("/{plugin_name}/projects/{project_id}/actions/{action_name}")
def run_plugin_action(
    plugin_name: str,
    project_id: str,
    action_name: str,
    body: dict,
    _user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
) -> dict:
    """Run a named plugin action (e.g. writeback) for a specific project."""
    try:
        cls = get_plugin(plugin_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown plugin: {plugin_name!r}")

    valid_actions = {a["name"] for a in cls.plugin_actions()}
    if action_name not in valid_actions:
        raise HTTPException(status_code=422, detail=f"Plugin {plugin_name!r} does not support action {action_name!r}")

    cfg_store = SQLitePluginConfigStore(session)
    saved_cfg = cfg_store.get(project_id, plugin_name)
    if saved_cfg is None:
        raise HTTPException(status_code=422, detail="No plugin config found for this project")

    plugin = cls(saved_cfg.config)
    return plugin.run_action(action_name, project_id, session, body)
