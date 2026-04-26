from __future__ import annotations

import logging
import logging.handlers

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from verdikt.api.routers import admin, ai_rating, auth, export, models, pipeline, plugins, profile, projects, rating, storage, works
from verdikt.core.config import AppConfig


def _configure_logging(config: AppConfig) -> None:
    try:
        config.ensure_dirs()
        file_handler: logging.Handler | None = logging.handlers.RotatingFileHandler(
            config.log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        file_handler = None  # data_dir not yet writable (tests / first run before dirs created)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s - %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    if file_handler is not None:
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
            root.addHandler(file_handler)

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
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(models.router)
    app.include_router(projects.router)
    app.include_router(export.router)
    app.include_router(plugins.router)
    app.include_router(works.router)
    app.include_router(pipeline.router)
    app.include_router(rating.router)
    app.include_router(profile.router)
    app.include_router(storage.router)
    app.include_router(ai_rating.router)

    if config.frontend_dir and config.frontend_dir.is_dir():
        _frontend_root = config.frontend_dir.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            candidate = (_frontend_root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(_frontend_root):
                return FileResponse(candidate)
            return FileResponse(_frontend_root / "index.html")

    return app


app = create_app()
