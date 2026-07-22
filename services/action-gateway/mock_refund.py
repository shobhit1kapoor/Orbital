from __future__ import annotations

import os
from typing import Any, Literal
from uuid import uuid4

from fastapi import Header, HTTPException
from orbital_semconv import ATTRIBUTES, SPANS, traced
from orbital_shared.api import create_service
from orbital_shared.models import Correlation, ToolReceipt, sha256_digest
from pydantic import BaseModel

app = create_service("ORBITAL Σ Local Mock Refund Fixture", "orbital-mock-refund-service")
FIXTURE_KEY = os.getenv("LOCAL_FIXTURE_KEY", "orbital-local-fixture")
receipts: dict[str, ToolReceipt] = {}


class SyntheticRefundRequest(BaseModel):
    correlation: Correlation
    tenant_id: str
    order_id: str
    amount: float
    fixture_scenario: Literal["semantic_effect_mismatch"]


@app.post("/v1/refunds")
def issue_synthetic_refund(
    request: SyntheticRefundRequest, x_orbital_fixture_key: str = Header(default="")
) -> dict[str, Any]:
    if x_orbital_fixture_key != FIXTURE_KEY:
        raise HTTPException(403, "local fixture authentication failed")
    if (
        request.tenant_id != "tenant-demo"
        or request.order_id != "ORD-2041"
        or request.amount != 900.0
    ):
        raise HTTPException(422, "only the deterministic owned demo fixture is accepted")
    idempotency_key = request.correlation.action_id
    if idempotency_key in receipts:
        return {
            "receipt": receipts[idempotency_key].model_dump(mode="json"),
            "idempotent_replay": True,
        }
    attributes = {
        ATTRIBUTES["mission_id"]: request.correlation.mission_id,
        ATTRIBUTES["action_id"]: request.correlation.action_id,
        ATTRIBUTES["action_type"]: "issue_refund",
        ATTRIBUTES["risk_class"]: "financial_irreversible",
        "orbital.fixture.synthetic": True,
        "orbital.refund.amount": request.amount,
    }
    with traced(SPANS["commit"], attributes):
        result = {
            "order_id": request.order_id,
            "amount": request.amount,
            "external_reference": f"synthetic_refund_{uuid4().hex[:8]}",
        }
        receipt = ToolReceipt(
            correlation=request.correlation,
            tool="issue_refund",
            amount=request.amount,
            external_reference=result["external_reference"],
            result_hash=sha256_digest(result),
            signature=sha256_digest({"fixture": True, **result}),
        )
        receipts[idempotency_key] = receipt
    return {"receipt": receipt.model_dump(mode="json"), "fixture_only": True}
