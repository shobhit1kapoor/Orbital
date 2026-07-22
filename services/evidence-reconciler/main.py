from __future__ import annotations

from typing import Any

from orbital_shared.api import create_service
from orbital_shared.assurance import classify_evidence
from orbital_shared.database import ObjectStore
from orbital_shared.models import (
    Correlation,
    EvidenceClaim,
    EvidenceParityResult,
    EvidenceState,
)
from pydantic import BaseModel

app = create_service("ORBITAL Σ PARALLAX Evidence Reconciler", "orbital-evidence-reconciler")
store = ObjectStore()


class EvidenceInput(BaseModel):
    correlation: Correlation
    semantic_action: str | None
    observed_action: str | None
    policy_allowed: bool | None
    receipt_verified: bool | None
    obi_observed: bool | None
    required_sensors_available: bool = True


def reconcile_evidence(value: EvidenceInput) -> EvidenceClaim:
    state, reasons = classify_evidence(
        semantic_action=value.semantic_action,
        observed_action=value.observed_action,
        policy_allowed=value.policy_allowed,
        receipt_verified=value.receipt_verified,
        obi_observed=value.obi_observed,
        required_sensors_available=value.required_sensors_available,
    )
    return EvidenceClaim(
        correlation=value.correlation,
        claim_type="consequential_action_parity",
        semantic_action=value.semantic_action,
        observed_action=value.observed_action,
        policy_allowed=value.policy_allowed,
        receipt_verified=value.receipt_verified,
        obi_observed=value.obi_observed,
        state=state,
        reasons=reasons,
    )


@app.post("/v1/evidence/reconcile")
def reconcile(value: EvidenceInput) -> dict[str, Any]:
    claim = reconcile_evidence(value)
    store.put(claim.claim_id, "evidence_claim", claim.model_dump(mode="json"), claim.created_at)
    return claim.model_dump(mode="json")


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
    return result.model_dump(mode="json")
