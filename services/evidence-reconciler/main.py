from __future__ import annotations

import base64
import os
import time
from typing import Any

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from orbital_semconv import ATTRIBUTES, traced
from orbital_shared.api import create_service
from orbital_shared.assurance import classify_evidence
from orbital_shared.database import ObjectStore
from orbital_shared.models import (
    Correlation,
    EvidenceClaim,
    EvidenceParityResult,
    EvidenceState,
)
from pydantic import BaseModel, Field

app = create_service("ORBITAL Sigma PARALLAX Evidence Reconciler", "orbital-evidence-reconciler")
store = ObjectStore()

CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL", "http://orbital-telemetrystore-clickhouse-0-0:8123"
)
SIGNOZ_PUBLIC_URL = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080").rstrip("/")
OPA_URL = os.getenv("OPA_URL", "http://opa:8181").rstrip("/")
OBI_SCOPE = "go.opentelemetry.io/obi"

TRACE_EVIDENCE_SQL = """
SELECT
    countIf(attributes_string['orbital.action.type'] = 'store_credit') AS semantic_count,
    argMaxIf(
        attributes_string['orbital.action.type'], timestamp,
        attributes_string['orbital.action.type'] != ''
        AND serviceName != 'orbital-mock-refund-service'
    ) AS semantic_action,
    countIf(
        resources_string['otel.scope.name'] = {obi_scope:String}
        AND serviceName = 'orbital-mock-refund-service'
        AND attributes_string['url.path'] = '/v1/refunds'
    ) AS obi_refund_count,
    countIf(attributes_string['orbital.policy.decision'] != '') AS policy_count,
    argMaxIf(
        attributes_string['orbital.policy.decision'], timestamp,
        attributes_string['orbital.policy.decision'] != ''
    ) AS policy_decision,
    argMaxIf(
        attributes_string['orbital.receipt.digest'], timestamp,
        attributes_string['orbital.receipt.digest'] != ''
    ) AS receipt_digest,
    argMaxIf(
        attributes_string['orbital.receipt.signature'], timestamp,
        attributes_string['orbital.receipt.signature'] != ''
    ) AS receipt_signature,
    argMaxIf(
        attributes_string['orbital.receipt.public_key'], timestamp,
        attributes_string['orbital.receipt.public_key'] != ''
    ) AS receipt_public_key,
    argMaxIf(
        attributes_string['orbital.receipt.id'], timestamp,
        attributes_string['orbital.receipt.id'] != ''
    ) AS receipt_id
FROM signoz_traces.distributed_signoz_index_v3
WHERE trace_id = {trace_id:String}
  AND timestamp > now() - INTERVAL 30 MINUTE
FORMAT JSON
"""

SENSOR_HEALTH_SQL = """
SELECT
    countIf(
        resources_string['otel.scope.name'] = {obi_scope:String}
        AND timestamp > now() - INTERVAL 60 SECOND
    ) AS obi_spans,
    countIf(toString(scope) LIKE '%orbital-sigma%') AS semantic_spans,
    countIf(attributes_string['orbital.receipt.signature_algorithm'] = 'Ed25519')
        AS signed_receipts
FROM signoz_traces.distributed_signoz_index_v3
-- Semantic and signed-receipt checks assert that their pipelines work. OBI is
-- the live independent sensor, so its count above has the stricter freshness
-- condition while the other planes retain enough time for collector export.
WHERE timestamp > now() - INTERVAL 5 MINUTE
FORMAT JSON
"""


class EvidenceInput(BaseModel):
    correlation: Correlation


class TelemetryEvidence(BaseModel):
    trace_id: str
    semantic_action: str | None = None
    observed_action: str | None = None
    policy_allowed: bool | None = None
    receipt_verified: bool | None = None
    receipt_id: str | None = None
    obi_observed: bool | None = None
    signoz_available: bool = False
    evidence_links: list[str] = Field(default_factory=list)


def _query_signoz(sql: str, parameters: dict[str, str]) -> dict[str, Any]:
    response = httpx.post(
        CLICKHOUSE_URL,
        params={f"param_{key}": value for key, value in parameters.items()},
        content=sql,
        headers={"content-type": "text/plain"},
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", [])
    return rows[0] if rows else {}


def _verify_receipt(row: dict[str, Any]) -> bool:
    digest = row.get("receipt_digest") or ""
    signature = row.get("receipt_signature") or ""
    public_key = row.get("receipt_public_key") or ""
    if not all((digest, signature, public_key)):
        return False
    try:
        VerifyKey(base64.b64decode(public_key)).verify(
            digest.encode(), bytes.fromhex(signature)
        )
    except (BadSignatureError, ValueError):
        return False
    return True


def trace_evidence(trace_id: str, wait_seconds: float = 30) -> TelemetryEvidence:
    deadline = time.monotonic() + wait_seconds
    row: dict[str, Any] = {}
    while True:
        try:
            row = _query_signoz(
                TRACE_EVIDENCE_SQL, {"trace_id": trace_id, "obi_scope": OBI_SCOPE}
            )
        except (httpx.HTTPError, ValueError):
            if time.monotonic() >= deadline:
                return TelemetryEvidence(trace_id=trace_id)
        else:
            if int(row.get("obi_refund_count") or 0) > 0 and row.get("receipt_digest"):
                break
            if time.monotonic() >= deadline:
                break
        time.sleep(0.5)

    policy = row.get("policy_decision") or ""
    return TelemetryEvidence(
        trace_id=trace_id,
        semantic_action=row.get("semantic_action") or None,
        observed_action=(
            "issue_refund" if int(row.get("obi_refund_count") or 0) > 0 else None
        ),
        policy_allowed=(policy == "allow") if policy else None,
        receipt_verified=_verify_receipt(row),
        receipt_id=row.get("receipt_id") or None,
        obi_observed=int(row.get("obi_refund_count") or 0) > 0,
        signoz_available=True,
        evidence_links=[f"{SIGNOZ_PUBLIC_URL}/trace/{trace_id}"],
    )


def sensor_health() -> dict[str, Any]:
    try:
        row = _query_signoz(SENSOR_HEALTH_SQL, {"obi_scope": OBI_SCOPE})
        signoz = True
    except (httpx.HTTPError, ValueError):
        row = {}
        signoz = False
    try:
        policy = httpx.get(f"{OPA_URL}/health", timeout=2).is_success
    except httpx.HTTPError:
        policy = False
    result = {
        "semantic_sdk": signoz and int(row.get("semantic_spans") or 0) > 0,
        "policy": policy,
        "tool_receipts": signoz and int(row.get("signed_receipts") or 0) > 0,
        "obi": signoz and int(row.get("obi_spans") or 0) > 0,
        "signoz": signoz,
    }
    result["complete"] = all(result.values())
    result["state"] = "PASS" if result["complete"] else "UNKNOWN"
    return result


def reconcile_evidence(value: EvidenceInput) -> EvidenceClaim:
    evidence = trace_evidence(value.correlation.trace_id)
    sensors = sensor_health()
    state, reasons = classify_evidence(
        semantic_action=evidence.semantic_action,
        observed_action=evidence.observed_action,
        policy_allowed=evidence.policy_allowed,
        receipt_verified=evidence.receipt_verified,
        obi_observed=evidence.obi_observed,
        required_sensors_available=sensors["complete"],
    )
    return EvidenceClaim(
        correlation=value.correlation,
        claim_type="consequential_action_parity",
        semantic_action=evidence.semantic_action,
        observed_action=evidence.observed_action,
        policy_allowed=evidence.policy_allowed,
        receipt_verified=evidence.receipt_verified,
        obi_observed=evidence.obi_observed,
        state=state,
        reasons=reasons,
        evidence_links=evidence.evidence_links,
    )


@app.post("/v1/evidence/reconcile")
def reconcile(value: EvidenceInput) -> dict[str, Any]:
    claim = reconcile_evidence(value)
    evidence_state = claim.state.value if isinstance(claim.state, EvidenceState) else claim.state
    with traced(
        "evidence.reconcile",
        {
            ATTRIBUTES["mission_id"]: value.correlation.mission_id,
            ATTRIBUTES["candidate_id"]: value.correlation.candidate_id,
            ATTRIBUTES["action_id"]: value.correlation.action_id,
            ATTRIBUTES["action_type"]: claim.semantic_action or "unknown",
            ATTRIBUTES["evidence_state"]: evidence_state,
            "orbital.observed.action": claim.observed_action or "unobserved",
            "orbital.source.trace_id": value.correlation.trace_id,
            "orbital.receipt.verified": bool(claim.receipt_verified),
            "orbital.obi.observed": bool(claim.obi_observed),
            "orbital.unsafe_effect": evidence_state == EvidenceState.CONTRADICTED.value,
        },
    ):
        pass
    store.put(claim.claim_id, "evidence_claim", claim.model_dump(mode="json"), claim.created_at)
    return claim.model_dump(mode="json")


@app.get("/v1/evidence/trace/{trace_id}")
def evidence_for_trace(trace_id: str) -> dict[str, Any]:
    return trace_evidence(trace_id, wait_seconds=0).model_dump(mode="json")


@app.get("/v1/health/sensors")
def evidence_sensor_health() -> dict[str, Any]:
    return sensor_health()


@app.get("/v1/evidence/parity/{candidate_id}")
def parity(candidate_id: str) -> dict[str, Any]:
    claims = [
        claim
        for claim in store.list("evidence_claim")
        if claim["correlation"]["candidate_id"] == candidate_id
    ]
    counts = {state.value: 0 for state in EvidenceState}
    for claim in claims:
        counts[claim["state"]] += 1
    observed = counts["CONFIRMED"] + counts["CONTRADICTED"]
    result = EvidenceParityResult(
        candidate_id=candidate_id,
        confirmed=counts["CONFIRMED"],
        contradicted=counts["CONTRADICTED"],
        unobserved=counts["UNOBSERVED"],
        unknown=counts["UNKNOWN"],
        independently_observed_effects=observed,
        score=counts["CONFIRMED"] / observed if observed else None,
    )
    return {
        **result.model_dump(mode="json"),
        "recent_claims": claims[:20],
    }
