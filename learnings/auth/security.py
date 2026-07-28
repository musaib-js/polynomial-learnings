"""Password hashing, JWT issuance/verification, and API-key generation.

Two different hashing schemes are used deliberately for two different threat
models:

* Passwords are low-entropy secrets checked rarely (once per login) -> argon2id
  (slow on purpose, resists offline brute force).
* API keys are high-entropy random secrets checked on *every* request to
  ``/v1/agents/*`` -> sha256 (fast, and entropy already makes brute force
  infeasible; a slow hash here would just add latency to every call).

``verify_api_key`` is the narrow seam a teammate's pip-package/backend
communication layer is expected to call (or replace) — see its docstring.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt

from ..settings import settings
from .models import AuthPrincipal
from .store import AuthStore

_API_KEY_PREFIX = "sk_live_"


# -- passwords ---------------------------------------------------------------


# argon2-cffi wraps a native (cffi) extension. Importing/instantiating it is
# deferred to first actual use rather than done at module import time, so
# merely importing learnings.auth.security (which learnings/api/app.py's
# import chain does even for routes that never touch passwords) doesn't pull
# a native extension into every process that imports the api package —
# e.g. one that also loads other native extensions (torch, via
# sentence-transformers) for embedding/reranking.
@lru_cache(maxsize=1)
def _get_hasher():
    from argon2 import PasswordHasher

    return PasswordHasher()


def hash_password(raw_password: str) -> str:
    return _get_hasher().hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    from argon2.exceptions import VerifyMismatchError

    try:
        return _get_hasher().verify(password_hash, raw_password)
    except VerifyMismatchError:
        return False


# -- JWT access tokens ---------------------------------------------------------


def create_access_token(user_id: str, org_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_access_token_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None


# -- opaque refresh / reset tokens --------------------------------------------


def generate_opaque_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hash)``. Only the hash is ever stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_opaque_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


# -- API keys ------------------------------------------------------------------


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(raw_key, key_prefix, key_hash)``.

    ``raw_key`` is shown to the caller exactly once; only ``key_hash`` is
    persisted (see ``api_keys.key_hash`` in the Alembic migration).
    """
    raw = _API_KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[: len(_API_KEY_PREFIX) + 8]
    return raw, key_prefix, key_hash


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key(raw_key: str, store: AuthStore) -> AuthPrincipal | None:
    """Resolve a raw API key to an :class:`AuthPrincipal`, or ``None``.

    This is the seam a teammate's library/backend communication layer is
    expected to call (directly, or via ``learnings.api.deps.get_api_key_principal``,
    which wraps this). It is intentionally narrow: given a raw key string, look
    up its hash, confirm it is not revoked/expired, and return the owning
    organization. The mechanics of *how* the pip package attaches the key to a
    request (header name, transport, etc.) are out of scope here — this
    function only answers "is this key good, and whose is it?"
    """
    key_hash = hash_api_key(raw_key)
    record = store.get_api_key_by_hash(key_hash)
    if record is None or not record.is_active:
        return None
    store.touch_api_key_last_used(record.id)
    return AuthPrincipal(org_id=record.org_id, api_key_id=record.id)
