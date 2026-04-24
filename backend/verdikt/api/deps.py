from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Generator

import chromadb
from sqlalchemy import create_engine, text as _text
from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from verdikt.core.config import AppConfig
from verdikt.storage.files import LocalStorageBackend, StorageBackend
from verdikt.storage.orm import Base

log = logging.getLogger(__name__)


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()


def _migrate(engine: Engine) -> None:
    """Apply additive schema migrations that create_all can't handle (new columns on existing tables)."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(_text("PRAGMA table_info(material_items)"))}

        if "plugin_metadata_json" not in existing:
            conn.execute(_text("ALTER TABLE material_items ADD COLUMN plugin_metadata_json TEXT NOT NULL DEFAULT '{}'"))
            conn.commit()
            log.info("migration: added plugin_metadata_json column")

        def _rating_cols() -> set[str]:
            return {row[1] for row in conn.execute(_text("PRAGMA table_info(ratings)"))}

        if "is_ai" not in _rating_cols():
            conn.execute(_text("ALTER TABLE ratings ADD COLUMN is_ai BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
            log.info("migration: added is_ai column to ratings")
        if "explanations" not in _rating_cols():
            conn.execute(_text("ALTER TABLE ratings ADD COLUMN explanations TEXT"))
            conn.commit()
            log.info("migration: added explanations column to ratings")

        # Backfill work_id from the old dedicated column into plugin_metadata_json for ao3 rows.
        # The work_id column was removed from the ORM but may still exist in the DB.
        if "work_id" in existing:
            rows = conn.execute(_text(
                "SELECT id, work_id, plugin_metadata_json FROM material_items "
                "WHERE work_id IS NOT NULL AND plugin_metadata_json = '{}'"
            )).fetchall()
            if rows:
                for row_id, work_id, _ in rows:
                    conn.execute(_text(
                        "UPDATE material_items SET plugin_metadata_json = :meta WHERE id = :id"
                    ), {"meta": json.dumps({"work_id": work_id}), "id": row_id})
                conn.commit()
                log.info("migration: backfilled work_id into plugin_metadata_json for %d rows", len(rows))


@lru_cache
def get_engine() -> Engine:
    config = get_config()
    config.ensure_dirs()
    engine = create_engine(f"sqlite:///{config.db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    _migrate(engine)
    return engine


def get_session(engine: Engine = Depends(get_engine)) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def get_chroma_client() -> chromadb.ClientAPI:
    config = get_config()
    return chromadb.PersistentClient(path=str(config.chroma_path))


def get_storage() -> StorageBackend:
    config = get_config()
    return LocalStorageBackend(config.user_files_path)
