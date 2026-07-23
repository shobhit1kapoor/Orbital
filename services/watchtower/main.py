from __future__ import annotations

import hashlib
import os
from typing import Any

from fastapi import Header, HTTPException
from orbital_semconv import ATTRIBUTES, SPANS, current_trace_ids, traced
from orbital_shared.api import create_service
from orbital_shared.database import ObjectStore, RolloutState
from orbital_shared.models import AttestationEvent, utcnow
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.watchtower.security import canonical_payload, verify_signature

app = create_service("ORBITAL Σ WATCHTOWER", "orbital-watchtower")
store = ObjectStore()
WEBHOOK_SECRET = os.getenv("ORBITAL_WEBHOOK_SECRET", "development-only")
SIGNOZ_PUBLIC_URL = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080").rstrip("/")


class RollbackRequest(BaseModel):
    certificate_id: str
    reason: str
    baseline_candidate_id: str = "baseline-v1"


def _baseline(certificate_id: str, candidate_id: str | None) -> tuple[str, str | None]:
    for certificate in store.list("certificate", 100):
        if certificate.get("certificate_id") == certificate_id:
            continue
        if candidate_id and certificate.get("candidate_id") == candidate_id:
            continue
        if certificate.get("verdict") in {"GO", "CONDITIONAL"}:
            return str(certificate["candidate_id"]), str(certificate["certificate_id"])
    return "baseline-v1", None


def _active_rollout() -> dict[str, Any] | None:
    with Session(store.engine) as session:
        rollout = session.get(RolloutState, "orbital.candidate.enabled")
        if rollout is None:
            return None
        return {
            "candidate_id": rollout.candidate_id,
            "enabled": rollout.enabled,
            "percentage": rollout.percentage,
            "certificate_id": rollout.certificate_id,
        }


def _rollback(
    certificate_id: str,
    reason: str,
    baseline: str | None = None,
    source_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_key = f"rollback:{certificate_id}"
    existing = store.get(event_key)
    if existing:
        return existing | {"idempotent_replay": True}
    source_event = source_event or {}
    active = _active_rollout()
    candidate_id = source_event.get("candidate_id") or (
        active.get("candidate_id") if active else None
    )
    resolved_baseline, baseline_certificate_id = _baseline(certificate_id, candidate_id)
    baseline = baseline or source_event.get("baseline_candidate_id") or resolved_baseline
    with Session(store.engine) as session:
        rollout = session.get(RolloutState, "orbital.candidate.enabled")
        if rollout is None:
            rollout = RolloutState(
                flag="orbital.candidate.enabled",
                candidate_id=baseline,
                enabled=True,
                percentage=100,
                certificate_id=baseline_certificate_id,
            )
            session.add(rollout)
        else:
            rollout.candidate_id = baseline
            rollout.enabled = True
            rollout.percentage = 100
            rollout.certificate_id = baseline_certificate_id
        session.commit()
    now = utcnow()
    evidence_links = list(source_event.get("evidence_links") or [])
    common = {
        ATTRIBUTES["certificate_id"]: certificate_id,
        ATTRIBUTES["candidate_id"]: candidate_id or "unknown",
        ATTRIBUTES["artifact_status"]: "drifted",
        ATTRIBUTES["execution_mode"]: "live",
        "orbital.signal.class": "rollback",
        "orbital.rollback.reason": reason,
        "orbital.alert.name": source_event.get("alertname") or reason,
        "orbital.webhook.delivery_id": source_event.get("delivery_id") or "manual",
    }
    with traced("watchtower.rollback", common):
        rollback_trace_id, _ = current_trace_ids()
        with traced(SPANS["suspend"], common):
            pass
        with traced(
            SPANS["rollout"],
            common
            | {
                "orbital.rollout.traffic_percentage": 0.0,
                "orbital.rollout.baseline_percentage": 100.0,
                "orbital.rollout.baseline_candidate_id": baseline,
            },
        ):
            pass
    if rollback_trace_id:
        evidence_links.append(f"{SIGNOZ_PUBLIC_URL}/trace/{rollback_trace_id}")
    payload = {
        "certificate_id": certificate_id,
        "candidate_id": candidate_id,
        "status": "suspended",
        "candidate_traffic_percentage": 0,
        "active_candidate": baseline,
        "active_baseline_certificate_id": baseline_certificate_id,
        "reason": reason,
        "alertname": source_event.get("alertname"),
        "alert_rule_id": source_event.get("rule_id"),
        "webhook_delivery_id": source_event.get("delivery_id"),
        "watchtower_trace_id": rollback_trace_id,
        "evidence_links": list(dict.fromkeys(evidence_links)),
        "replay_investigation_id": f"investigate-{certificate_id}",
        "rolled_back_at": now.isoformat(),
    }
    suspension = {
        "certificate_id": certificate_id,
        "candidate_id": candidate_id,
        "status": "suspended",
        "traffic_percentage": 0,
        "reason": reason,
        "suspended_at": now.isoformat(),
        "evidence_links": payload["evidence_links"],
    }
    store.put(event_key, "rollback", payload, now)
    store.put(f"certificate-state:{certificate_id}", "certificate_state", suspension, now)
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
    if not verify_signature(payload, WEBHOOK_SECRET, x_orbital_signature):
        raise HTTPException(401, "invalid webhook signature")
    delivery_id = str(
        payload.get("delivery_id")
        or hashlib.sha256(canonical_payload(payload)).hexdigest()
    )
    existing = store.get(f"webhook:{delivery_id}")
    duplicate_count = int(existing.get("duplicate_count", 1)) + 1 if existing else 1
    with traced(
        "signoz.webhook.accept",
        {
            ATTRIBUTES["execution_mode"]: "live",
            ATTRIBUTES["certificate_id"]: payload.get("certificate_id") or "active-rollout",
            "orbital.webhook.delivery_id": delivery_id,
            "orbital.webhook.signature_valid": True,
            "orbital.webhook.duplicate": existing is not None,
            "orbital.alert.name": payload.get("alertname") or "SigNoz safety alert",
            "orbital.signal.class": "certificate",
        },
    ):
        acceptance_trace_id, _ = current_trace_ids()
    active = _active_rollout()
    certificate_id = str(
        payload.get("certificate_id")
        or (active.get("certificate_id") if active else None)
        or "unknown"
    )
    result: dict[str, Any] = {
        "status": "acknowledged",
        "certificate_id": certificate_id,
    }
    if payload.get("status", "firing") == "firing":
        result = _rollback(
            certificate_id,
            str(payload.get("alertname") or "SigNoz safety alert"),
            payload.get("baseline_candidate_id"),
            payload | {"delivery_id": delivery_id},
        )
    now = utcnow()
    evidence_links = list(payload.get("evidence_links") or [])
    if acceptance_trace_id:
        evidence_links.append(f"{SIGNOZ_PUBLIC_URL}/trace/{acceptance_trace_id}")
    event = {
        "delivery_id": delivery_id,
        "source": "signoz",
        "signature_verified": True,
        "duplicate_count": duplicate_count,
        "duplicate_delivery": existing is not None,
        "status": payload.get("status", "firing"),
        "alertname": payload.get("alertname", "SigNoz safety alert"),
        "rule_id": payload.get("rule_id"),
        "certificate_id": certificate_id,
        "candidate_id": payload.get("candidate_id")
        or (active.get("candidate_id") if active else None),
        "trace_id": payload.get("trace_id"),
        "acceptance_trace_id": acceptance_trace_id,
        "evidence_links": list(dict.fromkeys(evidence_links + result.get("evidence_links", []))),
        "payload": payload,
        "received_at": existing.get("received_at") if existing else now.isoformat(),
        "last_received_at": now.isoformat(),
    }
    store.put(f"webhook:{delivery_id}", "webhook_event", event, now)
    return result | {
        "delivery_id": delivery_id,
        "duplicate_delivery": existing is not None,
        "duplicate_count": duplicate_count,
    }


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
        "suspensions": store.list("certificate_state", 20),
        "webhooks": store.list("webhook_event", 100),
    }
