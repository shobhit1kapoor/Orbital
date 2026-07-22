from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from orbital_shared.models import MissionContract, canonical_json, sha256_digest

SPAN_MATRIX = [
    "agent.mission",
    "context.load",
    "memory.read",
    "retrieval.search",
    "gen_ai.chat",
    "action.propose",
    "risk.quote",
    "policy.authorize",
    "action.bind",
    "capability.issue",
    "action.commit",
    "effect.verify",
]


@dataclass(frozen=True)
class CompilationResult:
    contract: MissionContract
    normalized_json: str
    contract_digest: str
    opa_data: dict[str, Any]
    span_matrix: list[str]
    evidence_claims: list[dict[str, Any]]
    query_builder: dict[str, Any]
    dashboards: dict[str, Any]
    alerts: list[dict[str, Any]]
    replay_catalogue: list[str]
    authority_tiers: list[dict[str, Any]]
    openfeature_rules: dict[str, Any]
    certificate_policy: dict[str, Any]
    ci_acceptance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.model_dump(mode="json"),
            "normalized_json": self.normalized_json,
            "contract_digest": self.contract_digest,
            "opa_data": self.opa_data,
            "span_matrix": self.span_matrix,
            "evidence_claims": self.evidence_claims,
            "query_builder": self.query_builder,
            "dashboards": self.dashboards,
            "alerts": self.alerts,
            "replay_catalogue": self.replay_catalogue,
            "authority_tiers": self.authority_tiers,
            "openfeature_rules": self.openfeature_rules,
            "certificate_policy": self.certificate_policy,
            "ci_acceptance": self.ci_acceptance,
        }


def _unwrap(raw: dict[str, Any]) -> dict[str, Any]:
    mission = raw.get("mission", {})
    artifacts = raw.get("artifacts", {})
    objectives = raw.get("objectives", {})
    certification = raw.get("certification", {})
    return {
        "name": mission["name"],
        "version": str(mission["version"]),
        "owner": mission["owner"],
        "objectives": {
            "task_success_minimum": objectives["task_success_rate"]["minimum"],
            "grounded_response_minimum": objectives["grounded_response_rate"]["minimum"],
            "p95_latency_ms_maximum": objectives["p95_latency_ms"]["maximum"],
            "cost_per_verified_resolution_usd_maximum": objectives[
                "cost_per_verified_resolution_usd"
            ]["maximum"],
        },
        "certification": certification,
        "authority": raw["authority"],
        "invariants": raw["invariants"],
        "failure_behavior": raw["failure_behavior"],
        "required_artifacts": sorted(
            key for key, value in artifacts.items() if value == "required"
        ),
        "certificate_ttl_hours": raw.get("certificate", {}).get("ttl_hours", 24),
        "maximum_canary_percentage": raw.get("deployment", {}).get("maximum_canary_percentage", 5),
    }


def compile_contract(raw: dict[str, Any]) -> CompilationResult:
    contract = MissionContract.model_validate(_unwrap(raw))
    normalized_json = canonical_json(contract.canonical_payload())
    contract_digest = sha256_digest(contract.canonical_payload())
    authority_tiers = [
        {"level": 0, "name": "READ_ONLY", "maximum_refund_usd": 0},
        {"level": 1, "name": "DRAFT", "maximum_refund_usd": 0},
        {"level": 2, "name": "REVERSIBLE_WRITE", "maximum_refund_usd": 0},
        {"level": 3, "name": "LOW_VALUE_ACTION", "maximum_refund_usd": 25},
        {"level": 4, "name": "HUMAN_APPROVED_IRREVERSIBLE", "maximum_refund_usd": 100},
        {"level": 5, "name": "AUTONOMOUS_IRREVERSIBLE", "maximum_refund_usd": 100},
    ]
    return CompilationResult(
        contract=contract,
        normalized_json=normalized_json,
        contract_digest=contract_digest,
        opa_data={
            "orbital": {
                "contract_digest": contract_digest,
                "authority": {key: value.model_dump() for key, value in contract.authority.items()},
                "invariants": contract.invariants,
            }
        },
        span_matrix=SPAN_MATRIX,
        evidence_claims=[
            {"claim": "authorization", "required_for": "irreversible"},
            {"claim": "effect_receipt", "required_for": "committed_action"},
            {"claim": "obi_observation", "required_for": "external_effect"},
            {"claim": "artifact_identity", "required_for": "all_missions"},
        ],
        query_builder={
            "missing_authorization": "action.commit NOT policy.authorize[policy.decision=allow]",
            "missing_verification": "action.commit[action.risk=irreversible] NOT effect.verify",
            "evidence_parity": "confirmed_external_effects / observed_external_effects",
        },
        dashboards={
            "variables": ["candidate_id", "certificate_id", "authority_level", "risk_class"]
        },
        alerts=[
            {"name": "Uncertified agent execution", "severity": "critical"},
            {"name": "Artifact drift", "severity": "critical"},
            {"name": "Missing authorization", "severity": "critical"},
            {"name": "Evidence mismatch", "severity": "critical"},
            {"name": "OBI sensor loss", "severity": "warning"},
        ],
        replay_catalogue=[
            "retrieval.poisoned_policy",
            "retrieval.stale_document",
            "memory.cross_tenant",
            "tool.hidden_side_effect",
            "tool.duplicate_execution",
            "infrastructure.timeout_after_commit",
            "multi_agent.authority_laundering",
        ],
        authority_tiers=authority_tiers,
        openfeature_rules={
            "flag": "orbital.candidate.enabled",
            "default": False,
            "maximum_canary_percentage": contract.maximum_canary_percentage,
        },
        certificate_policy={
            **contract.certification.model_dump(),
            "ttl_hours": contract.certificate_ttl_hours,
            "critical_violations_allowed": 0,
        },
        ci_acceptance={
            "require_signed_certificate": True,
            "accepted_verdicts": ["GO", "CONDITIONAL"],
            "reject_unknown": True,
        },
    )


def compile_contract_file(path: str | Path) -> CompilationResult:
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return compile_contract(raw)
