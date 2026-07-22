from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from orbital_semconv import ATTRIBUTES, traced
from orbital_shared.api import create_service

app = create_service("ORBITAL Sigma Signed Webhook Relay", "orbital-watchtower-relay")
security = HTTPBasic()
WATCHTOWER_URL = os.getenv("WATCHTOWER_URL", "http://watchtower:8000")
WEBHOOK_SECRET = os.getenv("ORBITAL_WEBHOOK_SECRET", "development-only")


def _assert_local_watchtower() -> None:
    parsed = urlparse(WATCHTOWER_URL)
    if parsed.scheme != "http" or parsed.hostname not in {"watchtower", "localhost", "127.0.0.1"}:
        raise RuntimeError("webhook relay is restricted to the local WATCHTOWER service")


@app.post("/v1/relay/signoz")
async def relay(
    payload: dict[str, Any],
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> dict[str, Any]:
    username_valid = hmac.compare_digest(credentials.username, "orbital-signoz")
    password_valid = hmac.compare_digest(credentials.password, WEBHOOK_SECRET)
    if not (username_valid and password_valid):
        raise HTTPException(401, "invalid local SigNoz relay credentials")
    _assert_local_watchtower()
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), repr(sorted(payload.items())).encode(), hashlib.sha256
    ).hexdigest()
    with traced(
        "signoz.webhook.relay",
        {
            ATTRIBUTES["execution_mode"]: "live",
            "orbital.webhook.signed": True,
            "orbital.signal.class": "certificate",
        },
    ):
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{WATCHTOWER_URL}/v1/webhooks/signoz",
                json=payload,
                headers={"x-orbital-signature": signature},
            )
            response.raise_for_status()
            return response.json()
