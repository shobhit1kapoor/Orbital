from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from orbital_shared.models import (
    AuthorityLevel,
    DelegationDecision,
    DelegationRequest,
    EvidenceState,
    sha256_digest,
)

AUTHORITY_INDEX = {
    AuthorityLevel.READ_ONLY: 0,
    AuthorityLevel.DRAFT: 1,
    AuthorityLevel.REVERSIBLE_WRITE: 2,
    AuthorityLevel.LOW_VALUE_ACTION: 3,
    AuthorityLevel.HUMAN_APPROVED_IRREVERSIBLE: 4,
    AuthorityLevel.AUTONOMOUS_IRREVERSIBLE: 5,
}

TOOL_MINIMUM_AUTHORITY = {
    "lookup_order": 0,
    "draft_recommendation": 1,
    "update_case": 2,
    "send_customer_email": 3,
    "issue_refund": 3,
}

PROHIBITED_DELEGATED_TOOLS = {
    "issue_capability",
    "modify_policy",
    "sign_certificate",
    "change_rollout",
}

CONSEQUENTIAL_TOOLS = {"send_customer_email", "issue_refund"}


def policy_input(
    request: DelegationRequest,
    *,
    parent_certificate_valid: bool | None,
    child_certificate_valid: bool | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(UTC)
    parent_authority = AUTHORITY_INDEX[
        AuthorityLevel(request.delegator.certificate.granted_authority)
    ]
    child_authority = AUTHORITY_INDEX[
        AuthorityLevel(request.delegate.certificate.granted_authority)
    ]
    delegated_authority = AUTHORITY_INDEX[AuthorityLevel(request.delegated_authority)]
    labels = set(request.data_labels)
    return {
        "delegation_id": request.delegation_id,
        "delegator_id": request.delegator.agent_id,
        "delegate_id": request.delegate.agent_id,
        "parent_authority": parent_authority,
        "child_authority": child_authority,
        "delegated_authority": delegated_authority,
        "delegated_tools": sorted(set(request.delegated_tools)),
        "parent_allowed_tools": sorted(set(request.delegator.allowed_tools)),
        "child_allowed_tools": sorted(set(request.delegate.allowed_tools)),
        "prohibited_tool": bool(
            set(request.delegated_tools).intersection(PROHIBITED_DELEGATED_TOOLS)
        ),
        "tool_authority_sufficient": all(
            TOOL_MINIMUM_AUTHORITY.get(tool, 99) <= delegated_authority
            for tool in request.delegated_tools
        ),
        "delegated_risk_budget": request.delegated_risk_budget,
        "parent_remaining_risk_budget": request.parent_remaining_risk_budget,
        "depth": request.delegation_depth,
        "maximum_depth": request.maximum_depth,
        "circular": request.delegate.agent_id in request.delegation_path,
        "same_tenant": request.delegator.tenant_id == request.delegate.tenant_id,
        "data_labels_allowed": (
            labels <= set(request.delegator.data_labels)
            and labels <= set(request.delegate.data_labels)
        ),
        "shared_memory_isolated": set(request.shared_memory_tenants)
        <= {request.delegator.tenant_id},
        "parent_identity_matches": (
            request.delegator.certificate.candidate_id == request.delegator.agent_id
            and request.delegator.claimed_artifact_digest
            == request.delegator.observed_artifact.digest
            == request.delegator.certificate.artifact.digest
        ),
        "child_identity_matches": (
            request.delegate.certificate.candidate_id == request.delegate.agent_id
            and request.delegate.claimed_artifact_digest
            == request.delegate.observed_artifact.digest
            == request.delegate.certificate.artifact.digest
        ),
        "parent_certificate_valid": parent_certificate_valid,
        "child_certificate_valid": child_certificate_valid,
        "consequential": bool(set(request.delegated_tools).intersection(CONSEQUENTIAL_TOOLS)),
        "not_expired": checked_at < request.expires_at,
        "ownership_present": bool(request.responsibility_owner),
    }


def evaluate_delegation(
    request: DelegationRequest,
    *,
    parent_certificate_valid: bool | None,
    child_certificate_valid: bool | None,
    opa_allowed: bool | None,
    now: datetime | None = None,
    trace_id: str = "",
    span_id: str = "",
    evidence_references: list[str] | None = None,
) -> DelegationDecision:
    values = policy_input(
        request,
        parent_certificate_valid=parent_certificate_valid,
        child_certificate_valid=child_certificate_valid,
        now=now,
    )
    detections: list[str] = []
    reasons: list[str] = []

    if values["child_authority"] > values["parent_authority"]:
        reasons.append("child_authority_exceeds_parent")
        detections.append("authority_laundering")
    if values["delegated_authority"] > values["parent_authority"]:
        reasons.append("delegated_authority_exceeds_parent")
        detections.append("authority_laundering")
    if not set(values["delegated_tools"]) <= set(values["parent_allowed_tools"]):
        reasons.append("delegated_tool_not_held_by_parent")
        detections.append("authority_laundering")
    if not set(values["delegated_tools"]) <= set(values["child_allowed_tools"]):
        reasons.append("delegate_not_permitted_for_tool")
        detections.append("prohibited_tool_delegation")
    if values["delegated_risk_budget"] > values["parent_remaining_risk_budget"]:
        reasons.append("delegated_risk_exceeds_parent_budget")
    if values["consequential"] and values["child_certificate_valid"] is not True:
        reasons.append("uncertified_child_cannot_receive_consequential_authority")
    if values["parent_certificate_valid"] is not True:
        reasons.append("parent_certificate_invalid")
    if values["depth"] > values["maximum_depth"]:
        reasons.append("delegation_depth_exceeded")
        detections.append("excessive_delegation_depth")
    if values["circular"]:
        reasons.append("circular_delegation")
        detections.append("circular_delegation")
    if not values["same_tenant"] or not values["data_labels_allowed"]:
        reasons.append("tenant_or_data_label_isolation_violation")
    if not values["parent_identity_matches"] or not values["child_identity_matches"]:
        reasons.append("certificate_or_artifact_identity_mismatch")
        detections.append("identity_spoofing")
    if values["prohibited_tool"]:
        reasons.append("prohibited_tool_delegation")
        detections.append("prohibited_tool_delegation")
    if not values["tool_authority_sufficient"]:
        reasons.append("conflicting_authority_scope")
        detections.append("conflicting_authority_scopes")
    if not values["shared_memory_isolated"]:
        reasons.append("shared_memory_tenant_contamination")
        detections.append("shared_memory_contamination")
    if not values["ownership_present"]:
        reasons.append("missing_responsibility_owner")
        detections.append("missing_ownership_or_responsibility")
    if not values["not_expired"]:
        reasons.append("delegation_expired")
    if opa_allowed is False:
        reasons.append("opa_denied")

    unavailable = (
        not request.evidence_available
        or parent_certificate_valid is None
        or child_certificate_valid is None
        or opa_allowed is None
    )
    if unavailable:
        state = EvidenceState.UNKNOWN
        allow = False
        reasons.append("required_delegation_evidence_unavailable")
    else:
        allow = not reasons and opa_allowed is True
        state = EvidenceState.CONFIRMED if allow else EvidenceState.CONTRADICTED
    return DelegationDecision(
        delegation_id=request.delegation_id,
        mission_id=request.mission_id,
        action_id=request.action_id,
        allow=allow,
        evidence_state=state,
        reasons=sorted(set(reasons)),
        detections=sorted(set(detections)),
        policy_input_digest=sha256_digest(values),
        opa_allowed=opa_allowed,
        parent_certificate_valid=parent_certificate_valid,
        child_certificate_valid=child_certificate_valid,
        trace_id=trace_id,
        span_id=span_id,
        evidence_references=evidence_references or [],
    )
