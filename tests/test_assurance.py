import pytest
from orbital_shared.assurance import (
    authority_conserved,
    classify_evidence,
    contains_sensitive_telemetry,
)
from orbital_shared.models import EvidenceState


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            dict(
                semantic_action="issue_refund",
                observed_action="issue_refund",
                policy_allowed=True,
                receipt_verified=True,
                obi_observed=True,
                required_sensors_available=True,
            ),
            EvidenceState.CONFIRMED,
        ),
        (
            dict(
                semantic_action="store_credit",
                observed_action="issue_refund",
                policy_allowed=None,
                receipt_verified=True,
                obi_observed=True,
                required_sensors_available=True,
            ),
            EvidenceState.CONTRADICTED,
        ),
        (
            dict(
                semantic_action="issue_refund",
                observed_action=None,
                policy_allowed=True,
                receipt_verified=False,
                obi_observed=True,
                required_sensors_available=True,
            ),
            EvidenceState.UNOBSERVED,
        ),
        (
            dict(
                semantic_action="issue_refund",
                observed_action="issue_refund",
                policy_allowed=True,
                receipt_verified=True,
                obi_observed=None,
                required_sensors_available=False,
            ),
            EvidenceState.UNKNOWN,
        ),
    ],
)
def test_evidence_classification(kwargs, expected):
    state, _ = classify_evidence(**kwargs)
    assert state == expected


def test_authority_conservation_blocks_laundering_and_cycles():
    allowed, reasons = authority_conserved(
        parent_authority=2,
        child_authority=5,
        parent_remaining_risk_budget=10,
        child_risk_budget=20,
        depth=4,
        maximum_depth=3,
        child_certified=False,
        circular=True,
    )
    assert not allowed
    assert set(reasons) == {
        "child_authority_exceeds_parent",
        "delegated_risk_exceeds_parent_budget",
        "delegation_depth_exceeded",
        "child_not_certified",
        "circular_delegation",
    }


def test_sensitive_telemetry_detection():
    assert contains_sensitive_telemetry({"raw_prompt": "secret", "orbital.risk.class": "low"}) == [
        "raw_prompt"
    ]
