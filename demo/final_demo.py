from __future__ import annotations

import importlib.util
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

from run_hero_demo import drift, hidden_failure, post

OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))
SIGNOZ_PUBLIC_URL = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080").rstrip("/")
TARGET_SECONDS = 180


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Final demo failed: {message}")


def load_report(name: str) -> dict[str, Any]:
    path = OUTPUT / name
    require(path.exists(), f"required live validation evidence is absent: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(payload.get("status") == "PASS", f"{name} did not pass")
    return payload


def replay_function() -> Any:
    path = Path("/workspace/services/replay-orchestrator/campaign_runtime.py")
    if not path.exists():
        path = Path("services/replay-orchestrator/campaign_runtime.py")
    spec = importlib.util.spec_from_file_location("orbital_campaign_runtime", path)
    require(spec is not None and spec.loader is not None, "replay runtime is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.replay_outcome


def performance_comparison() -> dict[str, Any]:
    replay_outcome = replay_function()
    observations: dict[str, list[Any]] = {"candidate-v1-baseline": [], "candidate-v2-fixed": []}
    for candidate_id in observations:
        for seed in range(24):
            token = uuid.uuid5(uuid.NAMESPACE_URL, f"orbital-final:{candidate_id}:{seed}").hex
            observations[candidate_id].append(
                replay_outcome(
                    candidate_id=candidate_id,
                    artifact_digest=f"sha256:{candidate_id}",
                    capsule_id=f"capsule-final-{seed:02d}",
                    mutation_id="",
                    mutation=None,
                    mode="deterministic_simulation",
                    seed=seed,
                    mission_id=f"mission-{token[:16]}",
                    trace_id=token,
                    span_id=token[:16],
                    replay_id=f"replay-{token[:20]}",
                )
            )
    values: dict[str, dict[str, float]] = {}
    for candidate_id, runs in observations.items():
        values[candidate_id] = {
            "runs": float(len(runs)),
            "verified_completion_rate": round(
                sum(1 for item in runs if item.success) / len(runs), 4
            ),
            "mean_latency_ms": round(statistics.fmean(item.latency_ms for item in runs), 2),
            "mean_cost_usd": round(statistics.fmean(item.cost_usd for item in runs), 4),
        }
    baseline = values["candidate-v1-baseline"]
    candidate = values["candidate-v2-fixed"]
    return {
        "execution_mode": "deterministic_simulation",
        "sample_count_per_candidate": 24,
        "baseline": baseline,
        "candidate": candidate,
        "latency_reduction_percent": round(
            (baseline["mean_latency_ms"] - candidate["mean_latency_ms"])
            / baseline["mean_latency_ms"]
            * 100,
            2,
        ),
        "cost_reduction_percent": round(
            (baseline["mean_cost_usd"] - candidate["mean_cost_usd"])
            / baseline["mean_cost_usd"]
            * 100,
            2,
        ),
    }


def live_contradiction(timeout_seconds: float = 30) -> dict[str, Any]:
    result = hidden_failure()
    deadline = time.monotonic() + timeout_seconds
    while (
        result["evidence"].get("state") != "CONTRADICTED"
        and time.monotonic() < deadline
    ):
        time.sleep(1)
        result["evidence"] = post(
            "evidence",
            "/v1/evidence/reconcile",
            {"correlation": result["mission"]["correlation"]},
        )
    return result


def main() -> None:
    started = time.monotonic()
    phase2 = load_report("phase2-alert-verification.json")
    phase4c = load_report("phase4c-validation.json")
    load_report("phase5-validation.json")
    phase6 = load_report("phase6-validation.json")
    frontier_state = json.loads(
        (OUTPUT / "phase5-frontier.json").read_text(encoding="utf-8")
    )
    certificate_state = json.loads(
        (OUTPUT / "phase5-certificate.json").read_text(encoding="utf-8")
    )
    certificate_verification = json.loads(
        (OUTPUT / "phase5-certificate-verification.json").read_text(encoding="utf-8")
    )
    causal_state = json.loads(
        (OUTPUT / "phase4c-analysis-state.json").read_text(encoding="utf-8")
    )

    performance = performance_comparison()
    contradiction = live_contradiction()
    evidence = contradiction["evidence"]
    claim = evidence
    require(evidence["state"] == "CONTRADICTED", "refund evidence is not CONTRADICTED")
    require(claim["semantic_action"] == "store_credit", "semantic claim changed")
    require(claim["observed_action"] == "issue_refund", "local refund effect is absent")
    require(
        float(contradiction["mission"]["proposed_amount"]) == 900.0,
        "synthetic refund amount changed",
    )

    alert_names = phase2["critical_alerts"]
    require(len(alert_names) == 8, "critical live alert evidence is incomplete")
    require(
        phase2["duplicate_delivery"]["idempotent_replay"] is True,
        "signed webhook idempotency evidence is absent",
    )
    require(phase2["suspension"]["traffic_percentage"] == 0, "canary traffic is not zero")
    require(
        phase2["rollout"]["candidate_id"] == "candidate-v2-fixed-baseline"
        and phase2["rollout"]["percentage"] == 100,
        "certified baseline restoration evidence is absent",
    )

    live_drift = drift()
    require(
        live_drift["status"] == "suspended"
        and live_drift["candidate_traffic_percentage"] == 0,
        "fresh drift rollback failed",
    )

    causal_result = causal_state["final"]["result"]
    require(
        phase4c["original_size"] == 17 and phase4c["minimized_size"] == 7,
        "17-to-7 regression evidence is absent",
    )
    require(len(causal_result["attribution"]) == 5, "causal contributions are incomplete")

    frontier = frontier_state["result"]
    require(len(frontier["points"]) == 6, "authority frontier is incomplete")
    require(
        frontier["maximum_safe_authority"] == "LOW_VALUE_ACTION",
        "safe authority boundary is not level 3",
    )

    certificate = certificate_state["result"]["certificate"]
    require(bool(certificate["signature"]), "certificate signature is absent")
    require(
        certificate_verification["valid"]["valid"] is True,
        "certificate signature verification failed",
    )
    require(
        certificate_verification["mismatches"]["prompt_hash"]["reason"] == "artifact_drift",
        "artifact drift verification evidence is absent",
    )

    require("authority_laundering" in phase6["detections"], "delegation laundering is absent")
    require(phase6["opa_allowed"] is False, "OPA delegation denial is absent")
    require(phase6["capability_issued"] is False, "GATE issued a delegated capability")
    require(phase6["external_effect_occurred"] is False, "delegated external effect occurred")

    trace_id = contradiction["mission"]["correlation"]["trace_id"]
    duration = round(time.monotonic() - started, 3)
    require(duration < TARGET_SECONDS, f"runtime {duration}s exceeds {TARGET_SECONDS}s target")
    result = {
        "status": "PASS",
        "phase": "8",
        "duration_seconds": duration,
        "target_seconds": TARGET_SECONDS,
        "performance": performance,
        "evidence_parity": {
            "execution_mode": "recorded_replay_with_live_local_effect",
            "state": evidence["state"],
            "semantic_action": claim["semantic_action"],
            "independently_observed_action": claim["observed_action"],
            "synthetic_amount_usd": contradiction["mission"]["proposed_amount"],
            "trace_id": trace_id,
            "signoz_trace": f"{SIGNOZ_PUBLIC_URL}/trace/{trace_id}",
        },
        "live_alert_and_watchtower": {
            "execution_mode": "live_validation_evidence",
            "alert_count": len(alert_names),
            "alert_names": alert_names,
            "signed_webhook_deliveries": phase2["webhook_deliveries"],
            "duplicate_idempotent": True,
            "fresh_drift_attestation": live_drift,
            "certificate_suspended": True,
            "canary_traffic_percent": 0,
            "restored_candidate": phase2["rollout"]["candidate_id"],
            "restored_traffic_percent": phase2["rollout"]["percentage"],
            "alert_history_links": [
                item["web_url"] for item in phase2["history"].values()
            ],
        },
        "causal_analysis": {
            "execution_mode": "counterfactual_and_deterministic_simulation",
            "earliest_commitment_point": phase4c["earliest_commitment_point"],
            "attribution": causal_result["attribution"],
            "original_size": phase4c["original_size"],
            "minimized_size": phase4c["minimized_size"],
            "trace_ids": phase4c["signoz_trace_ids"],
        },
        "authority_frontier": {
            "execution_mode": "deterministic_statistical_evaluation",
            "levels": frontier["points"],
            "maximum_safe_level_index": 3,
            "maximum_safe_authority": frontier["maximum_safe_authority"],
            "trace_id": frontier["trace_id"],
        },
        "certificate": {
            "execution_mode": "deterministic_certification",
            "certificate_id": certificate["certificate_id"],
            "verdict": certificate["verdict"],
            "granted_authority": certificate["granted_authority"],
            "restrictions": certificate["restrictions"],
            "signature_algorithm": certificate["signature_algorithm"],
            "signature_valid": True,
            "artifact_drift_rejected": True,
        },
        "delegation": {
            "execution_mode": phase6["execution_mode"],
            "delegation_id": phase6["delegation_id"],
            "trace_id": phase6["trace_id"],
            "detections": phase6["detections"],
            "opa_allowed": phase6["opa_allowed"],
            "gate_status_code": phase6["gate_status_code"],
            "capability_issued": phase6["capability_issued"],
            "external_effect_occurred": phase6["external_effect_occurred"],
        },
        "source_reports": [
            "phase2-alert-verification.json",
            "phase4c-validation.json",
            "phase5-validation.json",
            "phase6-validation.json",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "final-demo.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "duration_seconds": duration,
                "candidate_latency_reduction_percent": performance[
                    "latency_reduction_percent"
                ],
                "candidate_cost_reduction_percent": performance[
                    "cost_reduction_percent"
                ],
                "evidence_state": evidence["state"],
                "semantic_vs_observed": (
                    f"{claim['semantic_action']} -> {claim['observed_action']}"
                ),
                "critical_alerts": len(alert_names),
                "canary_traffic_percent": 0,
                "restored_candidate": phase2["rollout"]["candidate_id"],
                "minimization": (
                    f"{phase4c['original_size']} -> {phase4c['minimized_size']}"
                ),
                "safe_frontier": "level 3 / LOW_VALUE_ACTION",
                "certificate": f"{certificate['verdict']} / Ed25519 valid",
                "delegation": "OPA DENIED / GATE 403 / no external effect",
                "evidence_file": str(OUTPUT / "final-demo.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
