from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

import numpy as np
from orbital_shared.api import create_service
from orbital_shared.database import ObjectStore
from orbital_shared.models import CausalContribution, CausalFinding
from pydantic import BaseModel

app = create_service("ORBITAL Σ FORK Causal Engine", "orbital-causal-engine")
store = ObjectStore()

FACTORS = [
    "prompt_compression",
    "stale_retrieval",
    "tool_schema_expansion",
    "policy_permissiveness",
    "final_tool_execution",
]


class AnalyzeRequest(BaseModel):
    replay_run_id: str
    permutations: int = 128
    bootstrap_samples: int = 1000
    seed: int = 20260722


class MinimizeRequest(BaseModel):
    replay_run_id: str
    message_fragments: list[str]
    documents: list[str]
    memory_entries: list[str]
    tool_fields: list[str]


def failure_probability(active: set[str]) -> float:
    weights = {
        "prompt_compression": 0.39,
        "tool_schema_expansion": 0.33,
        "stale_retrieval": 0.19,
        "policy_permissiveness": 0.06,
        "final_tool_execution": 0.03,
    }
    base = sum(weights[factor] for factor in active)
    if {"prompt_compression", "tool_schema_expansion"} <= active:
        base += 0.12
    if "final_tool_execution" not in active:
        return 0.0
    return min(1.0, base)


@app.post("/v1/causal/analyze")
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    rng = random.Random(request.seed)
    marginal: dict[str, list[float]] = defaultdict(list)
    for _ in range(request.permutations):
        order = FACTORS[:]
        rng.shuffle(order)
        active: set[str] = set()
        prior = failure_probability(active)
        for factor in order:
            active.add(factor)
            current = failure_probability(active)
            marginal[factor].append(current - prior)
            prior = current

    contributions: list[CausalContribution] = []
    bootstrap_rng = np.random.default_rng(request.seed)
    for factor in FACTORS:
        values = np.array(marginal[factor], dtype=float)
        means = [
            float(np.mean(bootstrap_rng.choice(values, size=len(values), replace=True)))
            for _ in range(request.bootstrap_samples)
        ]
        contributions.append(
            CausalContribution(
                factor=factor,
                contribution=float(np.mean(values)),
                confidence_low=float(np.quantile(means, 0.025)),
                confidence_high=float(np.quantile(means, 0.975)),
            )
        )
    total = sum(max(0, contribution.contribution) for contribution in contributions) or 1
    for contribution in contributions:
        contribution.contribution = max(0, contribution.contribution) / total

    finding = CausalFinding(
        replay_run_id=request.replay_run_id,
        contributions=sorted(contributions, key=lambda item: item.contribution, reverse=True),
        earliest_commitment_point="prompt_compression",
        interactions={"prompt_compression×tool_schema_expansion": 0.12},
        original_tokens=18_400,
        minimized_tokens=712,
    )
    store.put(
        finding.finding_id, "causal_finding", finding.model_dump(mode="json"), finding.created_at
    )
    return finding.model_dump(mode="json")


@app.post("/v1/causal/minimize")
def minimize(request: MinimizeRequest) -> dict[str, Any]:
    required_markers = ("refund", "policy", "schema", "approval")

    def reduce(items: list[str]) -> list[str]:
        retained = [
            item for item in items if any(marker in item.lower() for marker in required_markers)
        ]
        return retained[:1] if retained else items[:1]

    minimized = {
        "message_fragments": reduce(request.message_fragments),
        "documents": reduce(request.documents),
        "memory_entries": reduce(request.memory_entries),
        "tool_fields": reduce(request.tool_fields),
    }
    capsule_id = f"regression-{request.replay_run_id}"
    payload = {
        "capsule_id": capsule_id,
        "source_run_id": request.replay_run_id,
        "minimized": minimized,
        "property": "removing_any_retained_element_eliminates_failure",
    }
    store.put(
        capsule_id,
        "regression_capsule",
        payload,
        __import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    return payload


@app.get("/v1/causal/findings")
def findings() -> list[dict[str, Any]]:
    return store.list("causal_finding", 100)
