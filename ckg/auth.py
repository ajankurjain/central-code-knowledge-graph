"""API token auth.

Tokens are 32-byte random base64url strings prefixed with `ckg_`.
We never store the raw token — only an argon2id hash.
The bootstrap token from CKG_BOOTSTRAP_TOKEN grants `admin` scope and is the
only way to mint the first real token; rotate it after first use.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select

from ckg.config import get_settings
from ckg.db.postgres import ApiToken, get_sessionmaker

_hasher = PasswordHasher()


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    name: str
    scopes: frozenset[str]
    token_id: int | None  # None = bootstrap

    def require(self, scope: str) -> None:
        if scope in self.scopes or "admin" in self.scopes:
            return
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"missing scope: {scope}"
        )


def generate_token() -> str:
    return "ckg_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return _hasher.hash(token)


def verify_token_hash(stored_hash: str, candidate: str) -> bool:
    try:
        _hasher.verify(stored_hash, candidate)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _bootstrap_match(candidate: str) -> bool:
    expected = get_settings().bootstrap_token
    if not expected:
        return False
    return hmac.compare_digest(candidate, expected)


def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """Resolve a Principal from either `Authorization: Bearer <tok>` or `X-API-Key`.

    Side-effect: stashes the resolved Principal on `request.state.principal`
    so the request-logging middleware (api/main.py) can attribute the call
    to a token without re-parsing the header. Failed auth leaves
    request.state unset, which the middleware treats as "anonymous".
    """

    candidate: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization.split(" ", 1)[1].strip()
    elif x_api_key:
        candidate = x_api_key.strip()

    if not candidate:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing API token")

    # Bootstrap token shortcut
    if _bootstrap_match(candidate):
        p = Principal(name="bootstrap", scopes=frozenset({"admin"}), token_id=None)
        request.state.principal = p
        return p

    # Look up in Postgres. We hash all non-revoked tokens and verify — at small scale
    # that is fine; at large scale you'd add a fast lookup column (e.g. an HMAC of the token).
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(
            select(ApiToken).where(ApiToken.revoked.is_(False))
        ).scalars().all()
        for row in rows:
            if verify_token_hash(row.token_hash, candidate):
                scopes = frozenset(p.strip() for p in row.scopes.split("|") if p.strip())
                p = Principal(name=row.name, scopes=scopes, token_id=row.id)
                request.state.principal = p
                return p

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid API token")


def require_admin(p: Principal = Depends(authenticate)) -> Principal:
    p.require("admin")
    return p


def require_repo_read(p: Principal = Depends(authenticate)) -> Principal:
    p.require("repo:read")
    return p


def require_repo_write(p: Principal = Depends(authenticate)) -> Principal:
    p.require("repo:write")
    return p
