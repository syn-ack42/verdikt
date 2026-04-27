from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Generator

import chromadb
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import create_engine, text as _text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from verdikt.core.config import AppConfig
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import AuthBase, UserRow
from verdikt.storage.files import EncryptedStorageBackend, StorageBackend
from verdikt.storage.orm import Base

log = logging.getLogger(__name__)

# Per-user engine cache: user_id → Engine
_user_engines: dict[str, Engine] = {}

# Track which users have had their files migrated this process lifetime
_files_migrated: set[str] = set()


def _derive_file_key(db_key: str) -> bytes:
    """Derive a 32-byte AES key for file encryption from the user's db_key.

    Uses HKDF-SHA256 with a dedicated info tag so the file key is distinct
    from the SQLCipher database key even though both derive from the same secret.
    """
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    raw = base64.b64decode(db_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"verdikt-file-encryption-v1",
    ).derive(raw)


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()


# ── Auth DB (plain SQLite, users table only) ────────────────────────────────

@lru_cache
def get_auth_engine() -> Engine:
    config = get_config()
    config.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{config.auth_db_path}",
        connect_args={"check_same_thread": False},
    )
    AuthBase.metadata.create_all(engine)
    _migrate_auth_db(engine)
    return engine


def _migrate_auth_db(engine: Engine) -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(_text("PRAGMA table_info(model_catalog)")).fetchall()}
        if "is_default" not in cols:
            conn.execute(_text("ALTER TABLE model_catalog ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0"))
            conn.commit()


def get_auth_session() -> Generator[Session, None, None]:
    with Session(get_auth_engine()) as session:
        yield session


# ── Per-user encrypted DB ───────────────────────────────────────────────────

def _make_user_engine(db_path: str, db_key: str) -> Engine:
    """Create a SQLCipher-encrypted SQLite engine for a user.

    Uses creator= so SQLAlchemy's sqlite dialect handles the connection without
    attempting its own PRAGMA key call. Falls back to plain SQLite when sqlcipher3
    is not installed (dev/no-encryption mode).
    """
    try:
        from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore

        def _creator():
            # check_same_thread must be passed directly — connect_args is ignored
            # when creator= is used, and sqlcipher3 enforces thread affinity at C level.
            conn = sqlcipher.connect(db_path, check_same_thread=False)
            conn.execute(f"PRAGMA key=\"{db_key}\"")
            return conn

        # Use plain sqlite:// dialect so SQLAlchemy doesn't inject its own PRAGMA key.
        # The creator= function overrides the connection path entirely.
        # NullPool: each Session gets a fresh connection; avoids StaticPool's single-connection
        # sharing which causes "Cannot operate on a closed database" under concurrent requests.
        engine = create_engine(
            "sqlite:///:memory:",
            creator=_creator,
            poolclass=NullPool,
        )
    except ImportError:
        log.warning("sqlcipher3 not installed — using plain SQLite (no encryption)")
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
    return engine


def get_user_engine(user: AuthenticatedUser) -> Engine:
    if user.id not in _user_engines:
        config = get_config()
        config.ensure_user_dirs(user.id)
        db_path = str(config.user_db_path(user.id))
        engine = _make_user_engine(db_path, user.db_key)
        Base.metadata.create_all(engine)
        _migrate_user_db(engine)
        _user_engines[user.id] = engine
    return _user_engines[user.id]


def _migrate_user_db(engine: Engine) -> None:
    """Apply additive schema migrations to a per-user DB."""
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

        def _project_cols() -> set[str]:
            return {row[1] for row in conn.execute(_text("PRAGMA table_info(projects)"))}

        if "min_profile_confidence" not in _project_cols():
            conn.execute(_text("ALTER TABLE projects ADD COLUMN min_profile_confidence REAL NOT NULL DEFAULT 0.9"))
            conn.commit()
            log.info("migration: added min_profile_confidence to projects")
        if "llm_model" not in _project_cols():
            conn.execute(_text("ALTER TABLE projects ADD COLUMN llm_model TEXT"))
            conn.commit()
            log.info("migration: added llm_model to projects")
        if "embedding_model" not in _project_cols():
            conn.execute(_text("ALTER TABLE projects ADD COLUMN embedding_model TEXT"))
            conn.commit()
            log.info("migration: added embedding_model to projects")

        def _profile_cols() -> set[str]:
            return {row[1] for row in conn.execute(_text("PRAGMA table_info(preference_profiles)"))}

        if "confirmed_count" not in _profile_cols():
            conn.execute(_text("ALTER TABLE preference_profiles ADD COLUMN confirmed_count INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
            log.info("migration: added confirmed_count to preference_profiles")
        if "score_sum" not in _profile_cols():
            conn.execute(_text("ALTER TABLE preference_profiles ADD COLUMN score_sum REAL NOT NULL DEFAULT 0.0"))
            conn.commit()
            log.info("migration: added score_sum to preference_profiles")

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


# ── Auth dependency ─────────────────────────────────────────────────────────

def get_current_user(request: Request) -> AuthenticatedUser:
    config = get_config()
    token = request.cookies.get("verdikt_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        user_id: str = payload["sub"]
        db_key: str = payload["key"]
        is_admin: bool = payload.get("admin", False)
        email: str = payload.get("email", "")
    except (JWTError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token")

    with Session(get_auth_engine()) as s:
        row = s.get(UserRow, user_id)
        if row is None or row.is_blocked:
            raise HTTPException(status_code=403, detail="Account blocked")

    return AuthenticatedUser(id=user_id, email=email, is_admin=is_admin, db_key=db_key)


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return user


# ── Session / storage dependencies (user-scoped) ───────────────────────────

def get_session(
    user: AuthenticatedUser = Depends(get_current_user),
) -> Generator[Session, None, None]:
    engine = get_user_engine(user)
    with Session(engine) as session:
        yield session


def get_chroma_client(
    user: AuthenticatedUser = Depends(get_current_user),
) -> chromadb.ClientAPI:
    config = get_config()
    return chromadb.PersistentClient(path=str(config.user_chroma_path(user.id)))


def get_storage(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Generator[StorageBackend, None, None]:
    config = get_config()
    key = _derive_file_key(user.db_key)
    backend = EncryptedStorageBackend(config.user_files_path(user.id), key, session)
    if user.id not in _files_migrated:
        _files_migrated.add(user.id)
        n = backend.migrate_plaintext_files()
        if n:
            log.info("migrated %d plaintext file(s) to encrypted storage for user %s", n, user.id)
    try:
        yield backend
    finally:
        backend.cleanup()
