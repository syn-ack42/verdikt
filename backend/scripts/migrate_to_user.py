#!/usr/bin/env python3
"""Migrate pre-auth verdikt data to a named user account.

Steps:
  1. Backup existing ~/.verdikt/verdikt.db to ~/.verdikt/backups/verdikt_premigration_<ts>.db
  2. Register or locate the target user in auth.db
  3. Copy verdikt.db to the user's directory and re-encrypt with SQLCipher
  4. Copy chroma/ and files/ directories to the user's directory

Usage:
    python scripts/migrate_to_user.py --email franz@franz-renger.de
    python scripts/migrate_to_user.py --email franz@franz-renger.de --password mypassword
"""
from __future__ import annotations

import argparse
import base64
import getpass
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _derive_key(password: str, kdf_salt_hex: str) -> str:
    from argon2.low_level import Type, hash_secret_raw
    raw = hash_secret_raw(
        secret=password.encode(),
        salt=bytes.fromhex(kdf_salt_hex),
        time_cost=2,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        type=Type.ID,
    )
    return base64.b64encode(raw).decode()


def _copy_sqlite_to_sqlcipher(src_path: Path, dst_path: Path, key: str) -> None:
    """Copy a plain SQLite database to an SQLCipher-encrypted one."""
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
        HAS_SQLCIPHER = True
    except ImportError:
        HAS_SQLCIPHER = False

    if HAS_SQLCIPHER:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        # Attach plain DB into SQLCipher and export
        enc_conn = sqlcipher.connect(str(dst_path))
        enc_conn.execute(f"PRAGMA key=\"{key}\"")
        enc_conn.execute(f"ATTACH DATABASE '{src_path}' AS plaintext KEY ''")
        enc_conn.execute("SELECT sqlcipher_export('main', 'plaintext')")
        enc_conn.execute("DETACH DATABASE plaintext")
        enc_conn.commit()
        enc_conn.close()
        print(f"  Encrypted DB written to {dst_path}")
    else:
        print("  WARNING: sqlcipher3 not installed — copying plain SQLite (no encryption)")
        shutil.copy2(src_path, dst_path)
        print(f"  Plain DB copied to {dst_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate pre-auth verdikt data to a user account")
    parser.add_argument("--email", required=True, help="Email address for the user account")
    parser.add_argument("--password", default=None, help="Password (prompted if not provided)")
    args = parser.parse_args()

    from verdikt.core.config import AppConfig
    config = AppConfig()
    config.ensure_dirs()

    src_db = config.db_path
    src_chroma = config.chroma_path
    src_files = config.legacy_files_path

    if not src_db.exists():
        print(f"No existing database found at {src_db}. Nothing to migrate.")
        return

    password = args.password or getpass.getpass(f"Password for {args.email}: ")

    # 1. Backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = config.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"verdikt_premigration_{ts}.db"
    shutil.copy2(src_db, backup_path)
    print(f"Backup created at {backup_path}")

    # 2. Register or locate user in auth.db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from verdikt.storage.auth_orm import AuthBase, UserRow

    auth_engine = create_engine(f"sqlite:///{config.auth_db_path}", connect_args={"check_same_thread": False})
    AuthBase.metadata.create_all(auth_engine)

    with Session(auth_engine) as s:
        existing = s.query(UserRow).filter_by(email=args.email).first()
        is_first_user = s.query(UserRow).count() == 0

        if existing is None:
            from argon2 import PasswordHasher
            ph = PasswordHasher()
            kdf_salt = uuid.uuid4().hex + uuid.uuid4().hex
            argon2_hash = ph.hash(password)
            db_key = _derive_key(password, kdf_salt)

            user = UserRow(
                id=str(uuid.uuid4()),
                email=args.email,
                argon2_hash=argon2_hash,
                kdf_salt=kdf_salt,
                is_admin=is_first_user,
                is_blocked=False,
                created_at=datetime.now(timezone.utc),
            )
            s.add(user)
            s.commit()
            print(f"Created user {args.email} (id={user.id}, admin={is_first_user})")
        else:
            # Verify password and derive key
            from argon2 import PasswordHasher
            ph = PasswordHasher()
            try:
                ph.verify(existing.argon2_hash, password)
            except Exception:
                print("ERROR: Incorrect password for existing user.")
                return
            db_key = _derive_key(password, existing.kdf_salt)
            user = existing
            print(f"Using existing user {args.email} (id={user.id})")

    user_id = user.id

    # 3. Copy DB to user directory (with encryption if sqlcipher3 available)
    config.ensure_user_dirs(user_id)
    dst_db = config.user_db_path(user_id)
    if dst_db.exists():
        overwrite = input(f"  {dst_db} already exists. Overwrite? [y/N] ").strip().lower()
        if overwrite != "y":
            print("Skipping DB migration.")
        else:
            _copy_sqlite_to_sqlcipher(src_db, dst_db, db_key)
    else:
        _copy_sqlite_to_sqlcipher(src_db, dst_db, db_key)

    # 4. Copy chroma directory
    dst_chroma = config.user_chroma_path(user_id)
    if src_chroma.exists():
        if dst_chroma.exists():
            print(f"  Chroma dir already exists at {dst_chroma}, skipping.")
        else:
            shutil.copytree(src_chroma, dst_chroma)
            print(f"  Chroma copied to {dst_chroma}")

    # 5. Copy files directory
    dst_files = config.user_files_path(user_id)
    if src_files.exists():
        if dst_files.exists():
            print(f"  Files dir already exists at {dst_files}, skipping.")
        else:
            shutil.copytree(src_files, dst_files)
            print(f"  Files copied to {dst_files}")

    # 6. Print summary
    plain_conn = sqlite3.connect(str(src_db))
    projects = plain_conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    materials = plain_conn.execute("SELECT COUNT(*) FROM material_items").fetchone()[0]
    ratings = plain_conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
    plain_conn.close()

    print(f"\nMigration complete:")
    print(f"  Projects : {projects}")
    print(f"  Materials: {materials}")
    print(f"  Ratings  : {ratings}")
    print(f"  User dir : {config.user_data_path(user_id)}")
    print(f"  Backup   : {backup_path}")


if __name__ == "__main__":
    main()
