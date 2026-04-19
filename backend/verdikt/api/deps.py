from __future__ import annotations

from functools import lru_cache
from typing import Generator

import chromadb
from sqlalchemy import create_engine
from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from verdikt.core.config import AppConfig
from verdikt.storage.orm import Base


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()


@lru_cache
def get_engine() -> Engine:
    config = get_config()
    config.ensure_dirs()
    engine = create_engine(f"sqlite:///{config.db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def get_session(engine: Engine = Depends(get_engine)) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def get_chroma_client() -> chromadb.ClientAPI:
    config = get_config()
    return chromadb.PersistentClient(path=str(config.chroma_path))
