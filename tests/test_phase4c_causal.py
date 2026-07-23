from __future__ import annotations

import json
from copy import deepcopy

import pytest
from orbital_shared.causal import (
    FACTORS,
    MODEL_PARAMETERS,
    aggregate_counterfactuals,
    failure_probability,
    hero_failure_context,
    hero_failure_signature,
    intervention_sets,
    minimize_hero_context,
    regression_capsule_payload,
    run_counterfactual,
    shapley_attribution,
    write_regression_capsule,
)
from orbital_shared.database import Base


def _complete_results(repeats: int = 32, seed: int = 20260723):
    return [
        run_counterfactual(interventions, seed + repeat).model_dump(mode="json")
        for interventions in intervention_sets()
        for repeat in range(repeats)
    ]


def test_counterfactual_runs_are_reproducible():
    first = run_counterfactual(["prompt_compression"], 41, MODEL_PARAMETERS)
    second = run_counterfactual(["prompt_compression"], 41, MODEL_PARAMETERS)
    assert first == second
    assert first.result_digest == second.result_digest


def test_single_and_pairwise_interventions_reduce_failure_risk():
    baseline = failure_probability([])
    singles = [failure_probability([factor]) for factor in FACTORS]
    pairs = [
        failure_probability(pair)
        for pair in intervention_sets()
        if len(pair) == 2
    ]
    assert all(value < baseline for value in singles)
    assert all(value <= max(singles) for value in pairs)
    assert (
        failure_probability(["prompt_compression", "tool_schema_change"])
        < failure_probability(["prompt_compression"])
    )


def test_confidence_intervals_and_earliest_commitment_point():
    aggregate = aggregate_counterfactuals(
        _complete_results(),
        repeat_count=32,
        shapley_samples=64,
        bootstrap_samples=300,
        seed=20260723,
    )
    assert aggregate.verdict == "CONFIRMED"
    assert len(aggregate.single_effects) == 5
    assert len(aggregate.pairwise_effects) == 10
    assert all(
        item.confidence_low <= item.contribution <= item.confidence_high
        for item in aggregate.single_effects + aggregate.pairwise_effects
    )
    assert aggregate.earliest_commitment_point == "prompt_compression"


def test_attribution_is_bounded_and_normalized():
    values = shapley_attribution(32, 200, 19)
    assert len(values) == 5
    assert sum(item.contribution for item in values) == pytest.approx(1.0, abs=1e-5)
    with pytest.raises(ValueError, match="sample count"):
        shapley_attribution(129, 20, 19)


def test_missing_counterfactual_evidence_is_unknown():
    aggregate = aggregate_counterfactuals(
        _complete_results()[:-1],
        repeat_count=32,
        shapley_samples=32,
        bootstrap_samples=100,
        seed=1,
    )
    assert aggregate.verdict == "UNKNOWN"
    assert not aggregate.evidence_complete
    assert not aggregate.attribution


def test_hero_minimizer_preserves_failure_and_is_one_minimal():
    original = hero_failure_context()
    result = minimize_hero_context(original, timebox_seconds=30)
    assert result["status"] == "COMPLETED"
    assert result["minimized_size"] < result["original_size"]
    assert hero_failure_signature(result["minimized"]) == result["failure_signature"]
    for category, values in result["minimized"].items():
        for index in range(len(values)):
            candidate = deepcopy(result["minimized"])
            candidate[category] = values[:index] + values[index + 1 :]
            assert hero_failure_signature(candidate) is None
    assert result["attempts"]


def test_retry_inputs_produce_identical_minimization():
    first = minimize_hero_context(timebox_seconds=30)
    second = minimize_hero_context(timebox_seconds=30)
    assert first["failure_signature"] == second["failure_signature"]
    assert first["minimized"] == second["minimized"]
    assert first["attempts"] == second["attempts"]


def test_phase4c_persistence_tables_are_registered():
    for name in {
        "causal_analyses",
        "causal_branches",
        "hero_minimizations",
        "hero_minimization_attempts",
    }:
        assert name in Base.metadata.tables


def test_regression_capsule_creation(tmp_path):
    minimized = minimize_hero_context(timebox_seconds=30)
    payload = regression_capsule_payload("analysis-test", minimized)
    path = write_regression_capsule(tmp_path, payload)
    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["failure_signature"] == hero_failure_signature(
        stored["minimized"]
    )
    assert stored["minimized_size"] < stored["original_size"]
