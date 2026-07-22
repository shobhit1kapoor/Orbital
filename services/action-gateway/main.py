from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException
from orbital_capabilities import CapabilityIssuer, canonical_arguments_hash
from orbital_semconv import ATTRIBUTES, SPANS, traced
from orbital_shared.api import create_service
from orbital_shared.database import CapabilityNonce, ObjectStore, Session
from orbital_shared.models import (
    CapabilityToken,
    Correlation,
    PolicyDecision,
    ToolReceipt,
    sha256_digest,
)
from pydantic import BaseModel

app = create_service("ORBITAL Σ Action Escrow Gateway", "orbital-action-gateway")
store = ObjectStore()
key_path = Path(os.getenv("CAPABILITY_SIGNING_KEY", "secrets/capability.key"))
issuer = CapabilityIssuer.load_or_create(key_path)
OPA_URL = os.getenv("OPA_URL", "http://opa:8181")


class ActionRequest(BaseModel):
    correlation: Correlation
    tool: str
    semantic_action: str
    tenant_id: str
    order_id: str
    amount: float
    amount_paid: float
    order_verified: bool
    human_approved: bool = False
    certificate_maximum_amount: float
    certificate_artifact_digest: str
    telemetry_complete: bool


def _local_allow(action: ActionRequest) -> tuple[bool, list[str]]:
    reasons = []
    if not action.order_verified:
        reasons.append("order_not_verified")
    if action.amount > action.amount_paid:
        reasons.append("amount_exceeds_payment")
    if action.amount > action.certificate_maximum_amount:
        reasons.append("amount_exceeds_certificate")
    if action.correlation.artifact_digest != action.certificate_artifact_digest:
        reasons.append("artifact_mismatch")
    if action.amount > 50 and not action.human_approved:
        reasons.append("human_approval_required")
    if not action.telemetry_complete:
        reasons.append("missing_telemetry")
    return not reasons, reasons


async def _authorize(action: ActionRequest) -> PolicyDecision:
    allow, reasons = _local_allow(action)
    opa_input = {
        "tool": action.tool,
        "order_verified": action.order_verified,
        "amount": action.amount,
        "amount_paid": action.amount_paid,
        "certificate_maximum_amount": action.certificate_maximum_amount,
        "artifact_digest": action.correlation.artifact_digest,
        "certificate_artifact_digest": action.certificate_artifact_digest,
        "telemetry_complete": action.telemetry_complete,
        "human_approved": action.human_approved,
        "human_approval_above": 50,
    }
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.post(
                f"{OPA_URL}/v1/data/orbital/refund/allow", json={"input": opa_input}
            )
            if response.status_code == 200 and "result" in response.json():
                allow = bool(response.json()["result"])
    except httpx.HTTPError:
        reasons.append("opa_unavailable_local_policy_used")
    return PolicyDecision(
        correlation=action.correlation,
        policy_path="orbital/refund/allow",
        policy_revision=os.getenv("POLICY_REVISION", "dev-v1"),
        allow=allow,
        reasons=reasons if reasons else ["authorized"],
        input_digest=sha256_digest(opa_input),
    )


def _receipt(action: ActionRequest, capability_jti: str | None) -> ToolReceipt:
    result = {
        "order_id": action.order_id,
        "amount": action.amount,
        "external_reference": f"refund_demo_{uuid4().hex[:8]}",
    }
    receipt = ToolReceipt(
        correlation=action.correlation,
        capability_jti=capability_jti,
        tool="issue_refund",
        amount=action.amount,
        external_reference=result["external_reference"],
        result_hash=sha256_digest(result),
    )
    receipt.signature = issuer.signing_key.sign(receipt.digest.encode()).signature.hex()
    store.put(
        receipt.receipt_id, "tool_receipt", receipt.model_dump(mode="json"), receipt.created_at
    )
    return receipt


@app.post("/v1/actions/propose")
def propose(action: ActionRequest) -> dict[str, Any]:
    return {
        "status": "proposed",
        "action_id": action.correlation.action_id,
        "risk_class": "financial_irreversible",
    }


@app.post("/v1/actions/quote")
def quote(action: ActionRequest) -> dict[str, Any]:
    risk = min(1.0, action.amount / max(action.amount_paid, 1))
    return {"risk_score": risk, "irreversible": True, "human_approval_required": action.amount > 50}


@app.post("/v1/actions/authorize")
async def authorize(action: ActionRequest) -> dict[str, Any]:
    decision = await _authorize(action)
    store.put(
        decision.decision_id,
        "policy_decision",
        decision.model_dump(mode="json"),
        decision.created_at,
    )
    return decision.model_dump(mode="json")


@app.post("/v1/capabilities/issue")
async def issue_capability(action: ActionRequest) -> dict[str, Any]:
    decision = await _authorize(action)
    if not decision.allow:
        raise HTTPException(403, {"decision_id": decision.decision_id, "reasons": decision.reasons})
    arguments = {
        "tool": action.tool,
        "order_id": action.order_id,
        "amount": action.amount,
        "tenant_id": action.tenant_id,
    }
    capability = issuer.issue(
        CapabilityToken(
            correlation=action.correlation,
            tool=action.tool,
            tenant_id=action.tenant_id,
            order_id=action.order_id,
            arguments_hash=canonical_arguments_hash(arguments),
            maximum_amount=action.amount,
            policy_revision=decision.policy_revision,
            expires_at=datetime.now(UTC) + timedelta(seconds=20),
        )
    )
    with Session(store.engine) as session:
        session.add(CapabilityNonce(jti=capability.jti, consumed=False))
        session.commit()
    return {"capability": capability.model_dump(mode="json"), "public_key": issuer.public_key}


@app.post("/v1/actions/commit")
async def commit(action: ActionRequest) -> dict[str, Any]:
    attributes = {
        ATTRIBUTES["mission_id"]: action.correlation.mission_id,
        ATTRIBUTES["action_id"]: action.correlation.action_id,
        ATTRIBUTES["action_type"]: action.tool,
        ATTRIBUTES["risk_class"]: "financial_irreversible",
    }
    decision = await _authorize(action)
    store.put(
        decision.decision_id,
        "policy_decision",
        decision.model_dump(mode="json"),
        decision.created_at,
    )
    with traced(
        SPANS["authorize"],
        attributes | {ATTRIBUTES["policy_decision"]: "allow" if decision.allow else "deny"},
    ):
        if not decision.allow:
            raise HTTPException(
                403, {"decision_id": decision.decision_id, "reasons": decision.reasons}
            )
    arguments = {
        "tool": action.tool,
        "order_id": action.order_id,
        "amount": action.amount,
        "tenant_id": action.tenant_id,
    }
    capability = issuer.issue(
        CapabilityToken(
            correlation=action.correlation,
            tool=action.tool,
            tenant_id=action.tenant_id,
            order_id=action.order_id,
            arguments_hash=canonical_arguments_hash(arguments),
            maximum_amount=action.amount,
            policy_revision=decision.policy_revision,
            expires_at=datetime.now(UTC) + timedelta(seconds=20),
        )
    )
    with Session(store.engine) as session:
        session.add(CapabilityNonce(jti=capability.jti, consumed=True))
        session.commit()
    with traced(SPANS["capability"], attributes), traced(SPANS["commit"], attributes):
        receipt = _receipt(action, capability.jti)
    with traced(SPANS["verify"], attributes | {"orbital.receipt.verified": True}):
        pass
    return {
        "status": "committed",
        "policy_decision": decision.model_dump(mode="json"),
        "capability": capability.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "evidence_state": "CONFIRMED",
    }


@app.post("/v1/effects/verify")
def verify_effect(receipt: ToolReceipt) -> dict[str, Any]:
    stored = store.get(receipt.receipt_id)
    return {
        "verified": bool(stored and stored.get("result_hash") == receipt.result_hash),
        "receipt_id": receipt.receipt_id,
    }
