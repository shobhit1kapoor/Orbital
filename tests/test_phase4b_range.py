from __future__ import annotations

import pytest
from orbital_shared.corpus import build_corpus
from orbital_shared.metamorphic import INVARIANTS, evaluate_invariant
from orbital_shared.range_evaluation import (
    BEAM_WIDTH,
    MAX_GENERATIONS,
    SELECTION_SIZE,
    AdaptiveProposal,
    evaluate_branch,
    fallback_proposals,
    rank_mutations,
    score_mutation,
    selection_digest,
    validate_selectable_mutation,
)
from orbital_shared.range_mutations import (
    DEFAULT_MUTATION_COUNT,
    build_mutations,
    mutation_catalogue_digest,
)
from pydantic import ValidationError


@pytest.fixture(scope="module")
def mutation_catalogue():
    mutations = [item[0] for item in build_mutations(build_corpus())]
    return mutations, mutation_catalogue_digest(mutations)


def test_all_880_safety_mutations_receive_six_factor_scores(mutation_catalogue):
    mutations, digest = mutation_catalogue
    scores, selected = rank_mutations(mutations, digest)
    assert len(mutations) == DEFAULT_MUTATION_COUNT == 880
    assert len(scores) == 880
    assert len(selected) == SELECTION_SIZE == 64
    assert all(len(item.factors.model_dump()) == 6 for item in scores)
    assert all(item.selectable for item in scores)


def test_ranking_and_top_64_selection_are_deterministic(mutation_catalogue):
    mutations, digest = mutation_catalogue
    first_scores, first = rank_mutations(mutations, digest)
    second_scores, second = rank_mutations(list(reversed(mutations)), digest)
    assert [item.mutation_id for item in first] == [
        item.mutation_id for item in second
    ]
    assert {item.mutation_id: item.score_digest for item in first_scores} == {
        item.mutation_id: item.score_digest for item in second_scores
    }
    assert selection_digest(first) == selection_digest(second)
    assert [(item.total_score, item.mutation_id) for item in first] == sorted(
        [(item.total_score, item.mutation_id) for item in first],
        key=lambda value: (-value[0], value[1]),
    )


def test_invalid_or_non_reproducible_mutations_cannot_be_selected(
    mutation_catalogue,
):
    mutation = mutation_catalogue[0][0]
    with pytest.raises(ValueError, match="invalid mutation"):
        validate_selectable_mutation(mutation.model_copy(update={"valid": False}))
    with pytest.raises(ValueError, match="non-reproducible"):
        validate_selectable_mutation(
            mutation.model_copy(update={"reproducible": False})
        )
    score = score_mutation(mutation.model_copy(update={"valid": False}), "catalogue")
    assert not score.selectable
    assert score.total_score == 0


def test_adaptive_loop_has_strict_beam_and_generation_budget(mutation_catalogue):
    mutation, digest = mutation_catalogue[0][0], mutation_catalogue[1]
    seed = score_mutation(mutation, digest)
    results = []
    for generation in range(1, MAX_GENERATIONS + 1):
        proposals = fallback_proposals(generation)
        assert len(proposals) == BEAM_WIDTH
        results.extend(evaluate_branch(seed, item) for item in proposals)
    assert len(results) == BEAM_WIDTH * MAX_GENERATIONS == 20
    assert all(item["reproducible"] for item in results)
    assert results[-1]["proposal"]["generation"] == MAX_GENERATIONS


def test_adaptive_proposals_reject_extra_or_misaligned_fields():
    payload = fallback_proposals(1)[0].model_dump()
    with pytest.raises(ValidationError):
        AdaptiveProposal.model_validate(payload | {"external_target": "forbidden"})
    with pytest.raises(ValidationError):
        AdaptiveProposal.model_validate(payload | {"beam_index": 1})


def test_every_specified_metamorphic_invariant_is_executable_and_passes():
    results = [evaluate_invariant(invariant) for invariant in INVARIANTS]
    assert len(results) == 9
    assert all(result.passed for result in results)
    assert len({result.result_digest for result in results}) == len(results)


@pytest.mark.parametrize("invariant", INVARIANTS)
def test_invariant_failures_are_detected(invariant):
    result = evaluate_invariant(invariant, unsafe_fixture=True)
    assert not result.passed


def test_timeout_retry_is_idempotent_and_reproducible():
    first = evaluate_invariant("tool_timeout_cannot_duplicate_transactions")
    second = evaluate_invariant("tool_timeout_cannot_duplicate_transactions")
    assert first.result_digest == second.result_digest
    assert first.after.transaction_ids == second.after.transaction_ids
    assert len(first.after.transaction_ids) == 1
