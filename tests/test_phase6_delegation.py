from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from orbital_shared.clearance import build_safety_case
from orbital_shared.database import Base
from orbital_shared.delegation import evaluate_delegation
from orbital_shared.models import (
    ArtifactIdentity,
    AuthorityLevel,
    DelegationAgentIdentity,
    DelegationRequest,
    EvidenceState,
    FlightCertificate,
    Verdict,
)

NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


def artifact(agent: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        agent_commit="8c192e7",
        container_digest=f"sha256:container-{agent}",
        prompt_hash=f"sha256:prompt-{agent}",
        model_identifier="qwen3:8b",
        model_digest="sha256:model",
        model_parameters_hash="sha256:params",
        tool_schema_hash="sha256:tools",
        policy_bundle_hash="sha256:policy",
        collector_config_hash="sha256:collector",
        mission_dataset_hash="sha256:missions",
        replay_engine_version="phase4.v1",
    )


def certificate(
    agent: str,
    authority: AuthorityLevel = AuthorityLevel.LOW_VALUE_ACTION,
) -> FlightCertificate:
    identity = artifact(agent)
    return FlightCertificate(
        certificate_id=f"ORB-{agent}",
        candidate_id=agent,
        artifact=identity,
        verdict=Verdict.GO,
        granted_authority=authority,
        maximum_refund_usd=25,
        canary_percentage=5,
        test_counts={"total": 1000},
        confidence_intervals={"unsafe_escape": (0.0, 0.003)},
        evidence_parity=1.0,
        grounded_response_rate=0.98,
        policy_completeness=1.0,
        mission_coverage=0.91,
        replay_fidelity=0.94,
        sensor_health=1.0,
        restrictions=["synthetic local fixtures only"],
        residual_risks=["bounded tested envelope"],
        safety_case=build_safety_case(
            candidate_id=agent,
            granted_authority=authority,
            metrics={"evidence_parity": 1.0},
            restrictions=["synthetic local fixtures only"],
            evidence_references=["signoz://trace/test"],
        ),
        expires_at=NOW + timedelta(hours=24),
    )


def identity(
    agent: str,
    *,
    authority: AuthorityLevel = AuthorityLevel.LOW_VALUE_ACTION,
    tenant: str = "tenant-demo",
    tools: list[str] | None = None,
) -> DelegationAgentIdentity:
    cert = certificate(agent, authority)
    return DelegationAgentIdentity(
        agent_id=agent,
        tenant_id=tenant,
        certificate=cert,
        observed_artifact=cert.artifact,
        claimed_artifact_digest=cert.artifact.digest,
        allowed_tools=tools or ["lookup_order", "issue_refund"],
        data_labels=["tenant:tenant-demo", "classification:synthetic"],
    )


def request(**changes) -> DelegationRequest:
    values = {
        "delegation_id": "dlg-test",
        "mission_id": "mis-test",
        "action_id": "act-test",
        "delegator": identity("parent"),
        "delegate": identity("child"),
        "delegated_tools": ["issue_refund"],
        "delegated_authority": AuthorityLevel.LOW_VALUE_ACTION,
        "delegated_risk_budget": 10.0,
        "parent_remaining_risk_budget": 20.0,
        "data_labels": ["tenant:tenant-demo"],
        "delegation_depth": 1,
        "maximum_depth": 3,
        "delegation_path": ["parent"],
        "expires_at": NOW + timedelta(minutes=5),
        "responsibility_owner": "parent",
        "shared_memory_tenants": ["tenant-demo"],
        "evidence_available": True,
    }
    values.update(changes)
    return DelegationRequest(**values)


def evaluate(value: DelegationRequest, **changes):
    values = {
        "parent_certificate_valid": True,
        "child_certificate_valid": True,
        "opa_allowed": True,
        "now": NOW,
    }
    values.update(changes)
    return evaluate_delegation(value, **values)


def test_valid_delegation_is_confirmed_and_reproducible():
    first = evaluate(request())
    second = evaluate(request())
    assert first.allow is True
    assert first.evidence_state == EvidenceState.CONFIRMED
    assert first.digest == second.digest


def test_authority_conservation_detects_laundering():
    parent = identity(
        "parent",
        authority=AuthorityLevel.REVERSIBLE_WRITE,
        tools=["lookup_order"],
    )
    result = evaluate(request(delegator=parent))
    assert result.allow is False
    assert "authority_laundering" in result.detections
    assert "delegated_tool_not_held_by_parent" in result.reasons


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"delegated_risk_budget": 21.0},
            "delegated_risk_exceeds_parent_budget",
        ),
        (
            {"delegation_path": ["parent", "child"]},
            "circular_delegation",
        ),
        (
            {"delegation_depth": 4},
            "delegation_depth_exceeded",
        ),
        (
            {"expires_at": NOW - timedelta(seconds=1)},
            "delegation_expired",
        ),
        (
            {"responsibility_owner": None},
            "missing_responsibility_owner",
        ),
        (
            {"shared_memory_tenants": ["tenant-other"]},
            "shared_memory_tenant_contamination",
        ),
    ],
)
def test_known_delegation_violations_are_denied(changes, reason):
    result = evaluate(request(**changes))
    assert result.allow is False
    assert result.evidence_state == EvidenceState.CONTRADICTED
    assert reason in result.reasons


def test_identity_mismatch_and_tenant_isolation():
    wrong_identity = identity("child")
    wrong_identity.agent_id = "spoofed-child"
    result = evaluate(
        request(
            delegate=wrong_identity,
            data_labels=["tenant:other"],
        )
    )
    assert "identity_spoofing" in result.detections
    assert "tenant_or_data_label_isolation_violation" in result.reasons


def test_uncertified_child_cannot_receive_consequential_authority():
    result = evaluate(request(), child_certificate_valid=False, opa_allowed=False)
    assert result.allow is False
    assert "uncertified_child_cannot_receive_consequential_authority" in result.reasons


def test_prohibited_tool_and_conflicting_scope_detection():
    prohibited = evaluate(
        request(
            delegated_tools=["modify_policy"],
            delegator=identity("parent", tools=["modify_policy"]),
            delegate=identity("child", tools=["modify_policy"]),
        ),
        opa_allowed=False,
    )
    assert "prohibited_tool_delegation" in prohibited.detections

    conflicting = evaluate(
        request(
            delegated_authority=AuthorityLevel.READ_ONLY,
            delegated_tools=["issue_refund"],
        ),
        opa_allowed=False,
    )
    assert "conflicting_authority_scopes" in conflicting.detections


def test_missing_evidence_is_unknown_and_never_allows():
    result = evaluate(
        request(evidence_available=False),
        parent_certificate_valid=None,
        child_certificate_valid=None,
        opa_allowed=None,
    )
    assert result.evidence_state == EvidenceState.UNKNOWN
    assert result.allow is False
    assert "required_delegation_evidence_unavailable" in result.reasons


def test_phase6_persistence_tables_are_registered():
    assert {"delegation_events", "delegation_evidence"} <= set(Base.metadata.tables)
