from __future__ import annotations

import hmac
import os
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from orbital_semconv import ATTRIBUTES, traced
from orbital_shared.api import create_service

from services.watchtower.security import normalize_signoz_payload, sign_payload

app = create_service("ORBITAL Sigma Signed Webhook Relay", "orbital-watchtower-relay")
security = HTTPBasic()
WATCHTOWER_URL = os.getenv("WATCHTOWER_URL", "http://watchtower:8000")
WEBHOOK_SECRET = os.getenv("ORBITAL_WEBHOOK_SECRET", "development-only")
SIGNOZ_PUBLIC_URL = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080")


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
    deliveries = []
    async with httpx.AsyncClient(timeout=10) as client:
        for normalized in normalize_signoz_payload(payload, SIGNOZ_PUBLIC_URL):
            signature = sign_payload(normalized, WEBHOOK_SECRET)
            with traced(
                "signoz.webhook.relay",
                {
                    ATTRIBUTES["execution_mode"]: "live",
                    ATTRIBUTES["certificate_id"]: normalized.get("certificate_id")
                    or "active-rollout",
                    "orbital.webhook.signed": True,
                    "orbital.webhook.delivery_id": normalized["delivery_id"],
                    "orbital.alert.name": normalized["alertname"],
                    "orbital.signal.class": "certificate",
                },
            ):
                response = await client.post(
                    f"{WATCHTOWER_URL}/v1/webhooks/signoz",
                    json=normalized,
                    headers={"x-orbital-signature": signature},
                )
                response.raise_for_status()
                deliveries.append(response.json())
    return {"deliveries": deliveries}
