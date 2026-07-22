from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import Header, HTTPException
from orbital_semconv import ATTRIBUTES, SPANS, traced
from orbital_shared.api import create_service
from orbital_shared.database import ObjectStore, RolloutState
from orbital_shared.models import AttestationEvent, utcnow
from pydantic import BaseModel
from sqlalchemy.orm import Session

app = create_service("ORBITAL Σ WATCHTOWER", "orbital-watchtower")
store = ObjectStore()
WEBHOOK_SECRET = os.getenv("ORBITAL_WEBHOOK_SECRET", "development-only")


class RollbackRequest(BaseModel):
    certificate_id: str
    reason: str
    baseline_candidate_id: str = "baseline-v1"


def _rollback(certificate_id: str, reason: str, baseline: str = "baseline-v1") -> dict[str, Any]:
    event_key = f"rollback:{certificate_id}:{reason}"
    existing = store.get(event_key)
    if existing:
        return existing | {"idempotent_replay": True}
    with Session(store.engine) as session:
        rollout = session.get(RolloutState, "orbital.candidate.enabled")
        if rollout is None:
            rollout = RolloutState(
                flag="orbital.candidate.enabled",
                candidate_id=baseline,
                enabled=True,
                percentage=100,
                certificate_id=None,
            )
            session.add(rollout)
        else:
            rollout.candidate_id = baseline
            rollout.enabled = True
            rollout.percentage = 100
            rollout.certificate_id = None
        session.commit()
    payload = {
        "certificate_id": certificate_id,
        "status": "suspended",
        "candidate_traffic_percentage": 0,
        "active_candidate": baseline,
        "reason": reason,
        "replay_investigation_id": f"investigate-{certificate_id}",
        "rolled_back_at": utcnow().isoformat(),
    }
    store.put(event_key, "rollback", payload, utcnow())
    common = {
        ATTRIBUTES["certificate_id"]: certificate_id,
        ATTRIBUTES["artifact_status"]: "drifted",
        ATTRIBUTES["execution_mode"]: "live",
        "orbital.signal.class": "rollback",
        "orbital.rollback.reason": reason,
    }
    with traced(SPANS["suspend"], common), traced(
        SPANS["rollout"], common | {"orbital.rollout.traffic_percentage": 0.0}
    ):
        pass
    return payload


@app.post("/v1/attestations")
def attest(event: AttestationEvent) -> dict[str, Any]:
    store.put(event.event_id, "attestation", event.model_dump(mode="json"), event.created_at)
    matches = event.expected_artifact_digest == event.observed_artifact_digest
    if matches:
        return {"status": "valid", "certificate_id": event.certificate_id}
    return _rollback(event.certificate_id, event.condition)


@app.post("/v1/webhooks/signoz")
async def signoz_webhook(
    payload: dict[str, Any], x_orbital_signature: str = Header(default="")
) -> dict[str, Any]:
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), repr(sorted(payload.items())).encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_orbital_signature):
        raise HTTPException(401, "invalid webhook signature")
    certificate_id = payload.get("certificate_id", "unknown")
    return _rollback(certificate_id, payload.get("alertname", "SigNoz safety alert"))


@app.post("/v1/certificates/{certificate_id}/suspend")
def suspend(certificate_id: str, reason: str = "manual suspension") -> dict[str, Any]:
    return _rollback(certificate_id, reason)


@app.post("/v1/rollbacks")
def rollback(request: RollbackRequest) -> dict[str, Any]:
    return _rollback(request.certificate_id, request.reason, request.baseline_candidate_id)


@app.get("/v1/runtime/status")
def status() -> dict[str, Any]:
    with Session(store.engine) as session:
        rollout = session.get(RolloutState, "orbital.candidate.enabled")
        rollout_payload = (
            {
                "candidate_id": rollout.candidate_id,
                "enabled": rollout.enabled,
                "percentage": rollout.percentage,
                "certificate_id": rollout.certificate_id,
            }
            if rollout
            else {
                "candidate_id": "baseline-v1",
                "enabled": True,
                "percentage": 100,
                "certificate_id": None,
            }
        )
    return {
        "rollout": rollout_payload,
        "attestations": store.list("attestation", 20),
        "rollbacks": store.list("rollback", 20),
    }
