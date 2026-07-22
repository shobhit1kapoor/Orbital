from __future__ import annotations

from typing import Any

from .models import EvidenceState


def classify_evidence(
    *,
    semantic_action: str | None,
    observed_action: str | None,
    policy_allowed: bool | None,
    receipt_verified: bool | None,
    obi_observed: bool | None,
    required_sensors_available: bool,
) -> tuple[EvidenceState, list[str]]:
    if not required_sensors_available or obi_observed is None:
        return EvidenceState.UNKNOWN, ["required_sensor_unavailable"]
    if observed_action and not semantic_action:
        return EvidenceState.CONTRADICTED, ["observed_effect_without_semantic_claim"]
    if semantic_action and not observed_action:
        return EvidenceState.UNOBSERVED, ["expected_effect_not_observed"]
    if semantic_action != observed_action:
        return EvidenceState.CONTRADICTED, ["semantic_and_observed_actions_disagree"]
    if observed_action and policy_allowed is not True:
        return EvidenceState.CONTRADICTED, ["effect_without_allow_decision"]
    if observed_action and receipt_verified is not True:
        return EvidenceState.UNOBSERVED, ["effect_receipt_missing_or_invalid"]
    return EvidenceState.CONFIRMED, ["independent_evidence_agrees"]


def authority_conserved(
    *,
    parent_authority: int,
    child_authority: int,
    parent_remaining_risk_budget: float,
    child_risk_budget: float,
    depth: int,
    maximum_depth: int,
    child_certified: bool,
    circular: bool,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if child_authority > parent_authority:
        failures.append("child_authority_exceeds_parent")
    if child_risk_budget > parent_remaining_risk_budget:
        failures.append("delegated_risk_exceeds_parent_budget")
    if depth > maximum_depth:
        failures.append("delegation_depth_exceeded")
    if not child_certified:
        failures.append("child_not_certified")
    if circular:
        failures.append("circular_delegation")
    return not failures, failures


def contains_sensitive_telemetry(attributes: dict[str, Any]) -> list[str]:
    forbidden = {
        "raw_prompt",
        "chain_of_thought",
        "capability_token",
        "payment_credentials",
        "customer_email",
        "customer_name",
    }
    return sorted(forbidden.intersection(attributes))
