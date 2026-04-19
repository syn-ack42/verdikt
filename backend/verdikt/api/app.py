from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from verdikt.api.routers import pipeline, profile, projects, rating, storage, works
from verdikt.core.config import AppConfig


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig()
    app = FastAPI(
        title="Verdikt API",
        root_path=config.root_path,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router)
    app.include_router(works.router)
    app.include_router(pipeline.router)
    app.include_router(rating.router)
    app.include_router(profile.router)
    app.include_router(storage.router)
    return app


app = create_app()
