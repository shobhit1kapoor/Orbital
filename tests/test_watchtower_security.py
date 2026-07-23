from orbital_shared.webhooks import (
    normalize_signoz_payload,
    sign_payload,
    verify_signature,
)


def test_webhook_signature_is_canonical_and_tamper_evident() -> None:
    first = {"status": "firing", "alertname": "ORBITAL Artifact Drift", "value": 2}
    reordered = {"value": 2, "alertname": "ORBITAL Artifact Drift", "status": "firing"}
    signature = sign_payload(first, "local-secret")
    assert signature == sign_payload(reordered, "local-secret")
    assert verify_signature(first, "local-secret", signature)
    assert not verify_signature(first | {"value": 3}, "local-secret", signature)


def test_signoz_payload_normalization_preserves_evidence_identity() -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "ORBITAL Evidence Mismatch",
                    "severity": "critical",
                    "trace_id": "a" * 32,
                    "orbital.certificate.id": "cert-phase2",
                    "orbital.candidate.id": "candidate-phase2",
                    "orbital.baseline.candidate.id": "baseline-v1",
                },
                "annotations": {"summary": "Synthetic local mismatch"},
                "generatorURL": (
                    "http://signoz:8080/alerts/overview?ruleId=rule-phase2"
                ),
                "fingerprint": "fixture-fingerprint",
            }
        ],
    }
    normalized = normalize_signoz_payload(payload, "http://localhost:8080")
    assert len(normalized) == 1
    event = normalized[0]
    assert event["certificate_id"] == "cert-phase2"
    assert event["candidate_id"] == "candidate-phase2"
    assert event["baseline_candidate_id"] == "baseline-v1"
    assert event["rule_id"] == "rule-phase2"
    assert event["trace_id"] == "a" * 32
    assert len(event["delivery_id"]) == 64
    assert len(event["evidence_links"]) == 3
