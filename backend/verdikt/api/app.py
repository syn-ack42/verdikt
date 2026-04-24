from __future__ import annotations

import logging
import logging.handlers

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from verdikt.api.routers import ai_rating, pipeline, plugins, profile, projects, rating, storage, works
from verdikt.core.config import AppConfig


def _configure_logging(config: AppConfig) -> None:
    config.ensure_dirs()
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s - %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        config.log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(file_handler)
    root.setLevel(logging.DEBUG)

    # Quiet down noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "multipart", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Downgrade high-frequency polling endpoints from INFO to DEBUG in the access log
    _POLL_PATHS = ("/update-plugin/status", "/crystallise/status", "/ai-rating/status")

    class _PollFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            args = record.args
            if isinstance(args, tuple) and len(args) >= 3:
                path = str(args[2]) if len(args) > 2 else ""
                if any(p in path for p in _POLL_PATHS):
                    record.levelno = logging.DEBUG
                    record.levelname = "DEBUG"
            return True

    logging.getLogger("uvicorn.access").addFilter(_PollFilter())


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig()
    _configure_logging(config)
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
    app.include_router(plugins.router)
    app.include_router(works.router)
    app.include_router(pipeline.router)
    app.include_router(rating.router)
    app.include_router(profile.router)
    app.include_router(storage.router)
    app.include_router(ai_rating.router)
    return app


app = create_app()
