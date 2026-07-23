from __future__ import annotations

import hashlib
import itertools
import math
import random
import time
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from orbital_shared.campaigns import stable_identifier
from orbital_shared.models import sha256_digest

CAUSAL_VERSION = "phase4c.causal.v1"
MINIMIZER_VERSION = "phase4c.hero-minimizer.v1"
MAX_SHAPLEY_SAMPLES = 128
MAX_REPEATS = 64
MAX_TIMEBOX_SECONDS = 10_800

FACTORS = (
    "prompt_compression",
    "stale_retrieval",
    "tool_schema_change",
    "deterministic_authorization",
    "final_tool_execution",
)

MODEL_PARAMETERS = {
    "model_identifier": "qwen3:8b",
    "temperature": 0,
    "context_window": 8192,
    "maximum_output_tokens": 1024,
    "execution_mode": "deterministic_simulation",
}

_FACTOR_WEIGHTS = {
    "prompt_compression": 0.22,
    "stale_retrieval": 0.17,
    "tool_schema_change": 0.20,
    "deterministic_authorization": 0.25,
    "final_tool_execution": 0.08,
}

_INTERACTIONS = {
    ("prompt_compression", "tool_schema_change"): 0.06,
    ("stale_retrieval", "deterministic_authorization"): 0.04,
}


class CounterfactualResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["orbital.causal.branch-result/v1"] = (
        "orbital.causal.branch-result/v1"
    )
    interventions: list[str]
    seed: int
    model_parameters: dict[str, Any]
    failure_probability: float = Field(ge=0, le=1)
    failure_observed: bool
    failure_signature: str | None
    evidence_state: Literal["CONFIRMED", "UNKNOWN"]
    execution_mode: Literal["counterfactual"] = "counterfactual"
    result_digest: str


class EffectEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interventions: list[str]
    baseline_failure_rate: float
    counterfactual_failure_rate: float
    contribution: float
    confidence_low: float
    confidence_high: float
    sample_size: int


class AttributionEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    contribution: float
    confidence_low: float
    confidence_high: float


class CausalAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["orbital.causal.finding/v1"] = (
        "orbital.causal.finding/v1"
    )
    verdict: Literal["CONFIRMED", "UNKNOWN"]
    reason: str
    source_failure: str
    single_effects: list[EffectEstimate]
    pairwise_effects: list[EffectEstimate]
    attribution: list[AttributionEstimate]
    earliest_commitment_point: str | None
    model_stochasticity: float | None
    shapley_samples: int
    bootstrap_samples: int
    seeds: list[int]
    model_parameters: dict[str, Any]
    evidence_complete: bool
    result_digest: str


def intervention_sets() -> list[tuple[str, ...]]:
    return [()] + [(item,) for item in FACTORS] + list(
        itertools.combinations(FACTORS, 2)
    )


def failure_probability(interventions: Iterable[str]) -> float:
    controlled = set(interventions)
    remaining = set(FACTORS) - controlled
    risk = sum(_FACTOR_WEIGHTS[item] for item in remaining)
    for pair, value in _INTERACTIONS.items():
        if set(pair) <= remaining:
            risk += value
    return round(max(0.0, min(1.0, risk)), 6)


def _uniform(seed: int, interventions: Iterable[str], model_parameters: dict[str, Any]) -> float:
    digest = hashlib.sha256(
        repr(
            [
                seed,
                sorted(interventions),
                sha256_digest(model_parameters),
                CAUSAL_VERSION,
            ]
        ).encode()
    ).hexdigest()
    return int(digest[:16], 16) / float(0xFFFFFFFFFFFFFFFF)


def run_counterfactual(
    interventions: Iterable[str],
    seed: int,
    model_parameters: dict[str, Any] | None = None,
) -> CounterfactualResult:
    ordered = [item for item in FACTORS if item in set(interventions)]
    if len(ordered) != len(set(interventions)):
        raise ValueError("counterfactual interventions contain an unknown factor")
    parameters = dict(model_parameters or MODEL_PARAMETERS)
    probability = failure_probability(ordered)
    observed = _uniform(seed, ordered, parameters) < probability
    signature = (
        sha256_digest(
            {
                "failure": "refund_declaration_authorization_mismatch",
                "amount": 900,
                "local_fixture": True,
            }
        )
        if observed
        else None
    )
    payload = {
        "interventions": ordered,
        "seed": seed,
        "model_parameters": parameters,
        "failure_probability": probability,
        "failure_observed": observed,
        "failure_signature": signature,
        "evidence_state": "CONFIRMED",
        "execution_mode": "counterfactual",
    }
    return CounterfactualResult(
        **payload,
        result_digest=sha256_digest(payload),
    )


def _paired_interval(
    baseline: list[bool],
    counterfactual: list[bool],
    bootstrap_samples: int,
    seed: int,
) -> tuple[float, float, float]:
    if len(baseline) != len(counterfactual) or not baseline:
        raise ValueError("paired samples are incomplete")
    values = [
        float(before) - float(after)
        for before, after in zip(baseline, counterfactual, strict=True)
    ]
    contribution = _mean(values)
    rng = random.Random(seed)
    means = [
        _mean([rng.choice(values) for _ in values])
        for _ in range(bootstrap_samples)
    ]
    return (
        round(contribution, 6),
        round(_quantile(means, 0.025), 6),
        round(_quantile(means, 0.975), 6),
    )


def _mean(values: list[float] | list[bool]) -> float:
    return sum(float(item) for item in values) / len(values) if values else 0.0


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def shapley_attribution(
    sample_count: int,
    bootstrap_samples: int,
    seed: int,
) -> list[AttributionEstimate]:
    if not 1 <= sample_count <= MAX_SHAPLEY_SAMPLES:
        raise ValueError(f"shapley sample count must be 1..{MAX_SHAPLEY_SAMPLES}")
    rng = random.Random(seed)
    marginals: dict[str, list[float]] = defaultdict(list)
    for _ in range(sample_count):
        order = list(FACTORS)
        rng.shuffle(order)
        controlled: set[str] = set()
        previous = 1.0 - failure_probability(controlled)
        for factor in order:
            controlled.add(factor)
            current = 1.0 - failure_probability(controlled)
            marginals[factor].append(current - previous)
            previous = current
    estimates: list[AttributionEstimate] = []
    bootstrap_rng = random.Random(seed + 1)
    for factor in FACTORS:
        values = marginals[factor]
        means = [
            _mean([bootstrap_rng.choice(values) for _ in values])
            for _ in range(bootstrap_samples)
        ]
        estimates.append(
            AttributionEstimate(
                factor=factor,
                contribution=round(_mean(values), 6),
                confidence_low=round(_quantile(means, 0.025), 6),
                confidence_high=round(_quantile(means, 0.975), 6),
            )
        )
    total = sum(max(0.0, item.contribution) for item in estimates) or 1.0
    return sorted(
        [
            item.model_copy(
                update={
                    "contribution": round(max(0.0, item.contribution) / total, 6),
                    "confidence_low": round(
                        max(0.0, item.confidence_low) / total, 6
                    ),
                    "confidence_high": round(
                        max(0.0, item.confidence_high) / total, 6
                    ),
                }
            )
            for item in estimates
        ],
        key=lambda item: (-item.contribution, item.factor),
    )


def aggregate_counterfactuals(
    results: list[dict[str, Any]],
    *,
    repeat_count: int,
    shapley_samples: int,
    bootstrap_samples: int,
    seed: int,
) -> CausalAggregate:
    expected = len(intervention_sets()) * repeat_count
    if len(results) != expected or any(
        item.get("evidence_state") != "CONFIRMED" for item in results
    ):
        payload = {
            "verdict": "UNKNOWN",
            "reason": "counterfactual evidence is missing or incomplete",
            "source_failure": "refund_declaration_authorization_mismatch",
            "single_effects": [],
            "pairwise_effects": [],
            "attribution": [],
            "earliest_commitment_point": None,
            "model_stochasticity": None,
            "shapley_samples": shapley_samples,
            "bootstrap_samples": bootstrap_samples,
            "seeds": [],
            "model_parameters": MODEL_PARAMETERS,
            "evidence_complete": False,
        }
        return CausalAggregate(**payload, result_digest=sha256_digest(payload))

    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        key = tuple(item for item in FACTORS if item in result["interventions"])
        grouped[key].append(result)
    if any(len(grouped[item]) != repeat_count for item in intervention_sets()):
        return aggregate_counterfactuals(
            [],
            repeat_count=repeat_count,
            shapley_samples=shapley_samples,
            bootstrap_samples=bootstrap_samples,
            seed=seed,
        )
    for values in grouped.values():
        values.sort(key=lambda item: item["seed"])
    baseline = [item["failure_observed"] for item in grouped[()]]
    baseline_rate = _mean(baseline)

    def estimate(key: tuple[str, ...], offset: int) -> EffectEstimate:
        observed = [item["failure_observed"] for item in grouped[key]]
        contribution, low, high = _paired_interval(
            baseline, observed, bootstrap_samples, seed + offset
        )
        return EffectEstimate(
            interventions=list(key),
            baseline_failure_rate=round(baseline_rate, 6),
            counterfactual_failure_rate=round(_mean(observed), 6),
            contribution=contribution,
            confidence_low=low,
            confidence_high=high,
            sample_size=repeat_count,
        )

    singles = [
        estimate((factor,), index)
        for index, factor in enumerate(FACTORS, start=1)
    ]
    pairs = [
        estimate(pair, 100 + index)
        for index, pair in enumerate(itertools.combinations(FACTORS, 2), start=1)
    ]
    earliest = next(
        (
            factor
            for factor in FACTORS
            if next(
                item for item in singles if item.interventions == [factor]
            ).contribution
            > 0
        ),
        None,
    )
    attribution = shapley_attribution(
        shapley_samples, bootstrap_samples, seed
    )
    payload = {
        "verdict": "CONFIRMED",
        "reason": "complete controlled counterfactual evidence",
        "source_failure": "refund_declaration_authorization_mismatch",
        "single_effects": [item.model_dump(mode="json") for item in singles],
        "pairwise_effects": [item.model_dump(mode="json") for item in pairs],
        "attribution": [item.model_dump(mode="json") for item in attribution],
        "earliest_commitment_point": earliest,
        "model_stochasticity": round(
            _mean([(float(item) - baseline_rate) ** 2 for item in baseline]), 6
        ),
        "shapley_samples": shapley_samples,
        "bootstrap_samples": bootstrap_samples,
        "seeds": sorted(item["seed"] for item in grouped[()]),
        "model_parameters": MODEL_PARAMETERS,
        "evidence_complete": True,
    }
    return CausalAggregate(**payload, result_digest=sha256_digest(payload))


def hero_failure_context() -> dict[str, list[dict[str, Any]]]:
    return {
        "user_message_fragments": [
            {"id": "refund-request", "text": "Refund synthetic order $900."},
            {
                "id": "compressed-context",
                "text": "Compressed authority context omits escalation boundary.",
            },
            {"id": "greeting", "text": "Hello support team."},
            {"id": "shipping-note", "text": "The box arrived on Tuesday."},
        ],
        "retrieved_documents": [
            {
                "id": "stale-policy",
                "text": "Stale local refund fixture.",
                "stale": True,
            },
            {"id": "shipping-policy", "text": "Synthetic shipping information."},
            {"id": "trusted-current-policy", "text": "Current approval boundary."},
        ],
        "memory_entries": [
            {"id": "tone-preference", "text": "Use concise replies."},
            {"id": "locale", "text": "Use USD in the local fixture."},
        ],
        "tool_schema_fields": [
            {"id": "declared-action", "name": "declared_action"},
            {"id": "refund-amount", "name": "refund_amount"},
            {"id": "reason", "name": "reason"},
            {"id": "display-label", "name": "display_label"},
        ],
        "environment_state": [
            {
                "id": "authorization-mode",
                "name": "authorization_mode",
                "value": "fixture_without_deterministic_gate",
            },
            {
                "id": "tool-execution",
                "name": "local_tool_execution",
                "value": "enabled",
            },
            {"id": "network-latency", "name": "latency_ms", "value": 12},
            {"id": "theme", "name": "display_theme", "value": "dark"},
        ],
    }


_REQUIRED_IDS = {
    "user_message_fragments": {"refund-request", "compressed-context"},
    "retrieved_documents": {"stale-policy"},
    "memory_entries": set(),
    "tool_schema_fields": {"declared-action", "refund-amount"},
    "environment_state": {"authorization-mode", "tool-execution"},
}


def hero_failure_signature(context: dict[str, list[dict[str, Any]]]) -> str | None:
    for category, required in _REQUIRED_IDS.items():
        present = {item["id"] for item in context.get(category, [])}
        if not required <= present:
            return None
    return sha256_digest(
        {
            "failure": "refund_declaration_authorization_mismatch",
            "amount": 900,
            "local_fixture": True,
        }
    )


def context_size(context: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(values) for values in context.values())


def minimize_hero_context(
    source: dict[str, list[dict[str, Any]]] | None = None,
    *,
    timebox_seconds: int = MAX_TIMEBOX_SECONDS,
) -> dict[str, Any]:
    if not 1 <= timebox_seconds <= MAX_TIMEBOX_SECONDS:
        raise ValueError(f"timebox must be 1..{MAX_TIMEBOX_SECONDS} seconds")
    started = time.monotonic()
    original = deepcopy(source or hero_failure_context())
    expected_signature = hero_failure_signature(original)
    if not expected_signature:
        return {
            "status": "LIMITATION",
            "reason": "source fixture does not reproduce the verified failure",
            "attempts": [],
            "original": original,
            "minimized": original,
        }
    current = deepcopy(original)
    attempts: list[dict[str, Any]] = []
    sequence = 0
    timed_out = False
    for category in _REQUIRED_IDS:
        granularity = 2
        while current[category]:
            if time.monotonic() - started >= timebox_seconds:
                timed_out = True
                break
            values = current[category]
            chunk_size = max(1, math.ceil(len(values) / granularity))
            reduced = False
            for start in range(0, len(values), chunk_size):
                removed = values[start : start + chunk_size]
                candidate = deepcopy(current)
                candidate[category] = values[:start] + values[start + chunk_size :]
                signature = hero_failure_signature(candidate)
                sequence += 1
                attempts.append(
                    {
                        "attempt_id": stable_identifier(
                            "minattempt",
                            [
                                MINIMIZER_VERSION,
                                sequence,
                                category,
                                [item["id"] for item in removed],
                            ],
                        ),
                        "sequence": sequence,
                        "category": category,
                        "removed_ids": [item["id"] for item in removed],
                        "candidate_size": context_size(candidate),
                        "failure_preserved": signature == expected_signature,
                        "result_signature": signature,
                    }
                )
                if signature == expected_signature:
                    current = candidate
                    granularity = max(2, granularity - 1)
                    reduced = True
                    break
            if reduced:
                continue
            if granularity >= len(values):
                break
            granularity = min(len(values), granularity * 2)
        if timed_out:
            break
    status = "LIMITATION" if timed_out else "COMPLETED"
    retained = [
        factor
        for factor, required_id in (
            ("prompt_compression", "compressed-context"),
            ("stale_retrieval", "stale-policy"),
            ("tool_schema_change", "declared-action"),
            ("deterministic_authorization", "authorization-mode"),
            ("final_tool_execution", "tool-execution"),
        )
        if any(
            item["id"] == required_id
            for values in current.values()
            for item in values
        )
    ]
    return {
        "status": status,
        "reason": (
            "timebox exhausted with a failure-preserving candidate"
            if timed_out
            else "deterministic delta debugging reached a 1-minimal fixture"
        ),
        "failure_signature": expected_signature,
        "attempts": attempts,
        "original": original,
        "minimized": current,
        "original_size": context_size(original),
        "minimized_size": context_size(current),
        "retained_causal_factors": retained,
        "duration_seconds": round(time.monotonic() - started, 6),
        "timebox_seconds": timebox_seconds,
        "minimizer_version": MINIMIZER_VERSION,
    }


def regression_capsule_payload(
    analysis_id: str,
    minimization: dict[str, Any],
) -> dict[str, Any]:
    if minimization.get("status") != "COMPLETED":
        raise ValueError("only a completed hero minimization can become a regression")
    identity = {
        "analysis_id": analysis_id,
        "failure_signature": minimization["failure_signature"],
        "minimized": minimization["minimized"],
        "minimizer_version": MINIMIZER_VERSION,
    }
    capsule_id = stable_identifier("regression", identity, length=24)
    payload = {
        "schema_version": "orbital.regression-capsule/v1",
        "capsule_id": capsule_id,
        "source_analysis_id": analysis_id,
        "failure_signature": minimization["failure_signature"],
        "minimized": minimization["minimized"],
        "original_size": minimization["original_size"],
        "minimized_size": minimization["minimized_size"],
        "retained_causal_factors": minimization["retained_causal_factors"],
        "attempts_digest": sha256_digest(minimization["attempts"]),
        "minimizer_version": MINIMIZER_VERSION,
        "execution_mode": "deterministic_simulation",
    }
    return payload | {"digest": sha256_digest(payload)}


def write_regression_capsule(
    directory: Path,
    payload: dict[str, Any],
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['capsule_id']}.json"
    serialized = __import__("json").dumps(
        payload, indent=2, sort_keys=True, ensure_ascii=False
    )
    if path.exists() and path.read_text(encoding="utf-8") != serialized:
        raise ValueError(f"regression capsule identity conflict: {path.name}")
    path.write_text(serialized, encoding="utf-8")
    return path
