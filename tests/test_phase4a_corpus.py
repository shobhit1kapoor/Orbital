from __future__ import annotations

import json
from collections import Counter

import pytest
from orbital_shared.corpus import (
    CORPUS_VERSION,
    EXPECTED_INVARIANTS,
    TEMPLATES,
    VARIANTS_PER_TEMPLATE,
    build_corpus,
    corpus_digest,
)
from orbital_shared.models import ReplayMutation
from orbital_shared.range_mutations import (
    DEFAULT_MUTATION_COUNT,
    DEFAULT_MUTATION_SEED,
    MutationRejected,
    apply_patch_document,
    build_mutations,
    category_counts,
    mutation_catalogue_digest,
    operator_catalog,
    operator_counts,
    validate_mutation,
)


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def generated(corpus):
    return build_mutations(corpus, DEFAULT_MUTATION_COUNT, DEFAULT_MUTATION_SEED)


def test_complete_corpus_is_deterministic(corpus) -> None:
    rebuilt = build_corpus()
    assert len(corpus) == len(TEMPLATES) * VARIANTS_PER_TEMPLATE == 120
    assert len({item.capsule_id for item in corpus}) == 120
    assert len({item.digest for item in corpus}) == 120
    assert [item.capsule_id for item in corpus] == [item.capsule_id for item in rebuilt]
    assert [item.digest for item in corpus] == [item.digest for item in rebuilt]
    assert corpus_digest(corpus) == corpus_digest(rebuilt)


def test_each_template_has_ten_complete_variants(corpus) -> None:
    template_counts = Counter(item.template for item in corpus)
    assert template_counts == Counter({template: 10 for template in TEMPLATES})
    required_cluster_features = {
        "intent",
        "tool_sequence",
        "authority",
        "outcome",
        "failure_type",
        "retrieval_topology",
        "escalation",
        "latency_bucket",
        "cost_bucket",
        "risk",
        "trace_shape",
    }
    for item in corpus:
        assert item.corpus_version == CORPUS_VERSION
        assert item.expected_invariants == EXPECTED_INVARIANTS
        assert len(item.retrieval_documents) == 3
        assert len(item.memory_snapshot) == 2
        assert set(item.cluster_features) == required_cluster_features
        assert item.privacy_map["capability_tokens"] == "never_export"
        assert item.external_api_cassette["payment"]["endpoint"].startswith(
            "http://mock-refund-service:"
        )


def test_operator_catalogue_covers_all_five_defined_families() -> None:
    counts = Counter(item.category for item in operator_catalog())
    assert counts == {
        "retrieval": 8,
        "memory": 6,
        "tool": 10,
        "infrastructure": 10,
        "multi-agent": 8,
    }
    assert sum(counts.values()) == 42


def test_880_mutations_have_unique_deterministic_identity_and_provenance(
    corpus, generated
) -> None:
    mutations = [item[0] for item in generated]
    rebuilt = [
        item[0]
        for item in build_mutations(
            list(reversed(corpus)),
            DEFAULT_MUTATION_COUNT,
            DEFAULT_MUTATION_SEED,
        )
    ]
    assert len(mutations) == 880
    assert len({item.mutation_id for item in mutations}) == 880
    assert len({item.digest for item in mutations}) == 880
    assert [item.mutation_id for item in mutations] == [
        item.mutation_id for item in rebuilt
    ]
    assert [item.digest for item in mutations] == [item.digest for item in rebuilt]
    assert mutation_catalogue_digest(mutations) == mutation_catalogue_digest(rebuilt)
    assert all(item.valid and item.reproducible for item in mutations)
    assert all(item.execution_mode == "deterministic_simulation" for item in mutations)
    assert all(item.provenance["mutation_id"] == item.mutation_id for item in mutations)
    assert all(
        item.provenance["mutated_fixture_digest"]
        == item.mutated_fixture_digest
        for item in mutations
    )


def test_all_operators_have_at_least_twenty_mutations(generated) -> None:
    mutations = [item[0] for item in generated]
    assert category_counts(mutations) == {
        "infrastructure": 210,
        "memory": 126,
        "multi-agent": 166,
        "retrieval": 168,
        "tool": 210,
    }
    counts = operator_counts(mutations)
    assert len(counts) == 42
    assert min(counts.values()) == 20
    assert max(counts.values()) == 21


def test_mutated_fixture_digest_matches_applied_patch(corpus, generated) -> None:
    by_id = {item.capsule_id: item for item in corpus}
    for mutation, persisted_fixture in generated:
        capsule = by_id[mutation.source_capsule_id]
        applied = apply_patch_document(
            capsule.model_dump(mode="json"),
            mutation.patch["operations"],
        )
        assert applied == persisted_fixture
        assert validate_mutation(mutation, capsule) == persisted_fixture


def test_invalid_operator_is_rejected(corpus, generated) -> None:
    mutation = generated[0][0].model_copy(
        update={"operator": "not_in_the_catalogue"}
    )
    source = next(
        item for item in corpus if item.capsule_id == mutation.source_capsule_id
    )
    with pytest.raises(MutationRejected, match="operator provenance"):
        validate_mutation(mutation, source)


def test_non_reproducible_mutation_is_rejected(corpus, generated) -> None:
    payload = generated[0][0].model_dump(mode="json")
    payload["digest"] = ""
    payload["mutated_fixture_digest"] = "sha256:" + ("0" * 64)
    mutation = ReplayMutation.model_validate(payload)
    source = next(
        item for item in corpus if item.capsule_id == mutation.source_capsule_id
    )
    with pytest.raises(MutationRejected, match="not reproducible"):
        validate_mutation(mutation, source)


def test_external_target_is_rejected(corpus, generated) -> None:
    candidate = next(
        mutation
        for mutation, _ in generated
        if mutation.operator == "hidden_side_effect"
    )
    payload = json.loads(candidate.model_dump_json())
    payload["digest"] = ""
    payload["patch"]["operations"][0]["value"]["endpoint"] = (
        "https://external.example/refunds"
    )
    mutation = ReplayMutation.model_validate(payload)
    source = next(
        item for item in corpus if item.capsule_id == mutation.source_capsule_id
    )
    with pytest.raises(MutationRejected, match="external target"):
        validate_mutation(mutation, source)


def test_patch_outside_category_boundary_is_rejected(corpus, generated) -> None:
    candidate = generated[0][0]
    payload = candidate.model_dump(mode="json")
    payload["digest"] = ""
    payload["patch"]["operations"][0]["path"] = "/tool_schemas/issue_refund/version"
    mutation = ReplayMutation.model_validate(payload)
    source = next(
        item for item in corpus if item.capsule_id == mutation.source_capsule_id
    )
    with pytest.raises(MutationRejected, match="cannot change root"):
        validate_mutation(mutation, source)
