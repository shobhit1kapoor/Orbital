from datetime import UTC, datetime, timedelta

import pytest
from orbital_capabilities import CapabilityIssuer, TokenError, canonical_arguments_hash
from orbital_shared.models import CapabilityToken, Correlation


def capability(expires_at):
    correlation = Correlation(candidate_id="candidate-v2-fixed", artifact_digest="sha256:artifact")
    return CapabilityToken(
        correlation=correlation,
        tool="issue_refund",
        tenant_id="tenant-demo",
        order_id="ORD-2041",
        arguments_hash=canonical_arguments_hash({"order_id": "ORD-2041", "amount": 25}),
        maximum_amount=25,
        policy_revision="v1",
        expires_at=expires_at,
    )


def test_capability_signature_and_argument_binding():
    issuer = CapabilityIssuer.generate()
    issued = issuer.issue(capability(datetime.now(UTC) + timedelta(seconds=20)))
    assert CapabilityIssuer.verify(issued, issuer.public_key)
    assert issued.arguments_hash != canonical_arguments_hash(
        {"order_id": "ORD-OTHER", "amount": 25}
    )


def test_expired_capability_is_rejected():
    issuer = CapabilityIssuer.generate()
    issued = issuer.issue(capability(datetime.now(UTC) - timedelta(seconds=1)))
    with pytest.raises(TokenError, match="expired"):
        CapabilityIssuer.verify(issued, issuer.public_key)


def test_tampered_capability_is_rejected():
    issuer = CapabilityIssuer.generate()
    issued = issuer.issue(capability(datetime.now(UTC) + timedelta(seconds=20)))
    tampered = issued.model_copy(update={"maximum_amount": 900})
    with pytest.raises(TokenError, match="invalid"):
        CapabilityIssuer.verify(tampered, issuer.public_key)
