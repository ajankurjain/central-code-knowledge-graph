"""Inbound webhook receiver — `POST /v1/webhooks/{source_id}`.

Unauthenticated against the API-token system on purpose: the provider
calls us with its own credentials shape (HMAC, shared token, URL token)
which we verify against the source's stored `webhook_secret`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ckg.db.postgres import AuditLog, BulkSource, get_sessionmaker
from ckg.logging import get_logger
from ckg.services import webhooks as wh

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger(__name__)


@router.post("/{source_id}")
async def receive(source_id: int, request: Request) -> dict:
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    query_token = request.query_params.get("secret")

    Session = get_sessionmaker()
    with Session() as s:
        source = s.get(BulkSource, source_id)
        if not source:
            raise HTTPException(404, "source not found")
        if not source.webhook_enabled or not source.webhook_secret:
            raise HTTPException(404, "webhook is not enabled for this source")
        secret = source.webhook_secret

    provider = wh.detect_provider(headers)
    if provider is None:
        raise HTTPException(400, "could not identify provider from request headers")

    if not wh.verify(provider, headers, body, secret, query_token):
        log.warning("webhook_verify_failed", source_id=source_id, provider=provider)
        raise HTTPException(401, "signature verification failed")

    event = wh.parse(provider, headers, body)
    if event is None:
        return {"accepted": True, "acted": False, "reason": "ignored event kind"}

    result = wh.handle_event(source_id, event)
    with Session() as s:
        s.add(AuditLog(
            actor=f"webhook:{provider}", action="webhook.received",
            target=str(source_id),
            detail={"provider": provider, "full_name": event.full_name, "ref": event.ref, **result},
        ))
        s.commit()
    return {"accepted": True, "acted": result.get("matched", False), **result}
