"""Symmetric encryption for third-party credentials (PATs).

We store users' GitHub / GitLab / Bitbucket personal-access tokens alongside
bulk sources so the worker can clone private repos. Storing them plaintext
in Postgres would be a regression on our standing security posture, so we
wrap them with Fernet (AES-128-CBC + HMAC-SHA256) keyed by
`CKG_SECRET_KEY`.

Trade-off: rotating the key requires re-saving every source's PAT. We
don't store key fingerprints today; Phase 5 will add key rotation.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ckg.config import get_settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = get_settings().secret_key.strip()
    if not key:
        raise RuntimeError("CKG_SECRET_KEY is not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Returns a Fernet-encrypted string. Safe to put in a database column."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Reverse of `encrypt`. Returns "" for empty input."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "could not decrypt — the CKG_SECRET_KEY in env does not match the one "
            "that encrypted this value. Rotate sources or restore the original key."
        ) from exc
