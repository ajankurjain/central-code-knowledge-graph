"""API-token management."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ckg.auth import Principal, generate_token, hash_token, require_admin
from ckg.db.postgres import ApiToken, AuditLog, get_sessionmaker

router = APIRouter(prefix="/tokens", tags=["auth"])


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["repo:read"])


class TokenCreated(BaseModel):
    id: int
    name: str
    scopes: list[str]
    token: str  # plaintext — shown ONCE
    created_at: datetime


class TokenInfo(BaseModel):
    id: int
    name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(body: TokenCreate, principal: Principal = Depends(require_admin)) -> TokenCreated:
    raw = generate_token()
    Session = get_sessionmaker()
    with Session() as s:
        row = ApiToken(
            name=body.name,
            token_hash=hash_token(raw),
            scopes="|".join(body.scopes),
        )
        s.add(row)
        s.flush()
        s.add(AuditLog(actor=principal.name, action="token.create", target=body.name, detail={"scopes": body.scopes}))
        s.commit()
        return TokenCreated(
            id=row.id,
            name=row.name,
            scopes=body.scopes,
            token=raw,
            created_at=row.created_at,
        )


@router.get("", response_model=list[TokenInfo])
def list_tokens(_: Principal = Depends(require_admin)) -> list[TokenInfo]:
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(select(ApiToken).order_by(ApiToken.id)).scalars().all()
        return [
            TokenInfo(
                id=r.id,
                name=r.name,
                scopes=[p for p in r.scopes.split("|") if p],
                created_at=r.created_at,
                last_used_at=r.last_used_at,
                revoked=r.revoked,
            )
            for r in rows
        ]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: int, principal: Principal = Depends(require_admin)) -> None:
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(ApiToken, token_id)
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
        row.revoked = True
        s.add(AuditLog(actor=principal.name, action="token.revoke", target=row.name))
        s.commit()
