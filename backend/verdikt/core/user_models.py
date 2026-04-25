from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuthenticatedUser:
    """Attached to every request that passes auth; carries the SQLCipher key in memory."""
    id: str
    email: str
    is_admin: bool = False
    # Base64-encoded 32-byte Argon2id-derived key — never persisted to disk.
    db_key: str = field(default="", repr=False)
