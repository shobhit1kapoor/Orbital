from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import HTTPException
from opentelemetry import metrics
from orbital_semconv import current_trace_ids, emit_event, traced
from orbital_shared.api import create_service
from orbital_shared.campaigns import stable_identifier, versioned_path
from orbital_shared.database import (
    CapsuleRecord,
    MutationRecord,
    ObjectStore,
)
from orbital_shared.models import MissionCapsule, ReplayMutation, sha256_digest
from orbital_shared.object_storage import IntegrityError, VersionedObjectStorage
from orbital_shared.range_mutations import (
    DEFAULT_MUTATION_COUNT,
    DEFAULT_MUTATION_SEED,
    MUTATION_CATALOG_VERSION,
    MutationRejected,
    build_mutations,
    category_counts,
    mutation_catalogue_digest,
    operator_catalog,
    operator_counts,
    validate_mutation,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

app = create_service(
    "ORBITAL Î£ RANGE Adversarial Foundry", "orbital-adversarial-foundry"
)
store = ObjectStore()
objects = VersionedObjectStorage()
meter = metrics.get_meter("orbital-adversarial-foundry")
mutations_accepted = meter.create_counter("orbital.mutation.accepted")
mutations_rejected = meter.create_counter("orbital.mutation.rejected")
mutation_duplicates = meter.create_counter("orbital.mutation.duplicate")
mutation_generation_latency = meter.create_histogram(
    "orbital.mutation.generation.duration",
    unit="ms",
    description="Deterministic mutation generation and persistence duration",
)

OPERATORS: dict[str, list[str]] = {}
for _spec in operator_catalog():
    OPERATORS.setdefault(_spec.category, []).append(_spec.name)


class MutationRequest(BaseModel):
    capsule_ids: list[str]
    target_count: int = Field(default=DEFAULT_MUTATION_COUNT, ge=1, le=5_000)
    seed: int = DEFAULT_MUTATION_SEED


class MutationValidationRequest(BaseModel):
    capsule_id: str
    mutation: ReplayMutation


class AdaptiveRequest(BaseModel):
    mutation_ids: list[str] | None = None
    top_k: int = 64
    beam_width: int = 4
    generations: int = 5


def _load_capsules(capsule_ids: list[str]) -> list[MissionCapsule]:
    unique_ids = list(dict.fromkeys(capsule_ids))
    if not unique_ids:
        raise HTTPException(422, "at least one capsule_id is required")
    if len(unique_ids) != len(capsule_ids):
        raise HTTPException(422, "capsule_ids must be unique")
    with Session(store.engine) as session:
        records = session.scalars(
            select(CapsuleRecord).where(CapsuleRecord.capsule_id.in_(unique_ids))
        ).all()
    by_id = {record.capsule_id: record for record in records}
    missing = sorted(set(unique_ids) - set(by_id))
    if missing:
        raise HTTPException(422, f"capsules are not persisted: {missing[:5]}")
    capsules: list[MissionCapsule] = []
    for capsule_id in unique_ids:
        record = by_id[capsule_id]
        try:
            manifest = objects.get_json(record.object_path, record.checksum)
        except IntegrityError as exc:
            raise HTTPException(
                409, f"corrupted source capsule rejected: {capsule_id}: {exc}"
            ) from exc
        try:
            capsule = MissionCapsule.model_validate(manifest["capsule"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                422, f"invalid source capsule schema: {capsule_id}"
            ) from exc
        if capsule.digest != record.content_digest:
            raise HTTPException(409, f"source capsule digest mismatch: {capsule_id}")
        capsules.append(capsule)
    return capsules


def _persist_mutation(
    mutation: ReplayMutation,
    mutated_fixture: dict[str, Any],
) -> tuple[bool, list[str]]:
    mutation_payload = mutation.model_dump(mode="json")
    mutation_path = versioned_path(
        "mutation-artifacts",
        mutation.mutation_id,
        mutation.digest,
        "mutation.json",
    )
    result_path = versioned_path(
        "mutation-artifacts",
        mutation.mutation_id,
        mutation.mutated_fixture_digest,
        "mutated-fixture.json",
    )
    mutation_result = objects.put_json(
        mutation_path,
        "mutation_artifact",
        mutation.mutation_id,
        mutation_payload,
    )
    fixture_result = objects.put_json(
        result_path,
        "mutation_result",
        mutation.mutation_id,
        mutated_fixture,
    )
    manifest = {
        "schema_version": "orbital.mutation.bundle/v1",
        "mutation_id": mutation.mutation_id,
        "mutation_digest": mutation.digest,
        "source_capsule_id": mutation.source_capsule_id,
        "source_capsule_digest": mutation.source_capsule_digest,
        "mutated_fixture_digest": mutation.mutated_fixture_digest,
        "provenance": mutation.provenance,
        "validation": mutation.validation,
        "artifacts": {
            "mutation.json": {
                key: mutation_result[key]
                for key in ("path", "checksum", "size_bytes")
            },
            "mutated-fixture.json": {
                key: fixture_result[key]
                for key in ("path", "checksum", "size_bytes")
            },
        },
    }
    manifest_path = versioned_path(
        "mutation-artifacts",
        mutation.mutation_id,
        mutation.digest,
        "manifest.json",
    )
    manifest_result = objects.put_json(
        manifest_path,
        "mutation_manifest",
        mutation.mutation_id,
        manifest,
    )
    provenance_digest = sha256_digest(mutation.provenance)
    with Session(store.engine) as session:
        existing = session.get(MutationRecord, mutation.mutation_id)
        created = existing is None
        if existing:
            if (
                existing.mutation_digest != mutation.digest
                or existing.provenance_digest != provenance_digest
                or existing.checksum != manifest_result["checksum"]
            ):
                raise MutationRejected(
                    f"mutation identity conflict: {mutation.mutation_id}"
                )
        else:
            session.add(
                MutationRecord(
                    mutation_id=mutation.mutation_id,
                    source_capsule_id=mutation.source_capsule_id,
                    source_capsule_digest=mutation.source_capsule_digest,
                    category=mutation.category,
                    operator=mutation.operator,
                    operator_version=mutation.operator_version,
                    seed=mutation.seed,
                    sequence=mutation.sequence,
                    provenance_digest=provenance_digest,
                    mutation_digest=mutation.digest,
                    mutated_fixture_digest=mutation.mutated_fixture_digest,
                    object_path=manifest_path,
                    checksum=manifest_result["checksum"],
                    valid=mutation.valid,
                    reproducible=mutation.reproducible,
                    payload=mutation_payload,
                    created_at=mutation.created_at,
                )
            )
        session.commit()
    store.put(
        mutation.mutation_id,
        "replay_mutation",
        mutation_payload,
        mutation.created_at,
    )
    return created, [mutation_path, result_path, manifest_path]


@app.post("/v1/mutations/generate")
def generate(request: MutationRequest) -> dict[str, Any]:
    started = perf_counter()
    capsules = _load_capsules(request.capsule_ids)
    with traced(
        "mutation.catalogue.generate",
        {
            "orbital.signal.class": "campaign",
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.mutation.catalog.version": MUTATION_CATALOG_VERSION,
            "orbital.mutation.target_count": request.target_count,
            "orbital.capsule.count": len(capsules),
            "orbital.risk.class": "high",
        },
    ):
        trace_id, _ = current_trace_ids()
        try:
            generated = build_mutations(
                capsules,
                target_count=request.target_count,
                seed=request.seed,
            )
        except MutationRejected as exc:
            mutations_rejected.add(1, {"orbital.mutation.reason": str(exc)[:80]})
            emit_event(
                "mutation.catalogue.rejected",
                reason=str(exc),
                seed=request.seed,
                target_count=request.target_count,
                trace_id=trace_id,
            )
            raise HTTPException(422, f"mutation catalogue rejected: {exc}") from exc

        created = 0
        object_paths: list[str] = []
        mutations: list[ReplayMutation] = []
        for mutation, mutated_fixture in generated:
            with traced(
                "mutation.operator.apply",
                {
                    "orbital.signal.class": "campaign",
                    "orbital.execution.mode": "deterministic_simulation",
                    "orbital.mutation.id": mutation.mutation_id,
                    "orbital.mutation.category": mutation.category,
                    "orbital.mutation.operator": mutation.operator,
                    "orbital.mutation.valid": True,
                    "orbital.mutation.reproducible": True,
                },
            ):
                was_created, paths = _persist_mutation(
                    mutation,
                    mutated_fixture,
                )
                created += int(was_created)
                object_paths.extend(paths)
                mutations.append(mutation)

        duplicates = len(mutations) - created
        mutations_accepted.add(created)
        mutation_duplicates.add(duplicates)
        mutation_generation_latency.record(
            (perf_counter() - started) * 1000,
            {"orbital.mutation.catalog.version": MUTATION_CATALOG_VERSION},
        )
        emit_event(
            "mutation.catalogue.persisted",
            catalog_version=MUTATION_CATALOG_VERSION,
            count=len(mutations),
            created=created,
            duplicates=duplicates,
            rejected=0,
            trace_id=trace_id,
        )
    return {
        "count": len(mutations),
        "created": created,
        "duplicates": duplicates,
        "rejected": 0,
        "catalog_version": MUTATION_CATALOG_VERSION,
        "catalogue_digest": mutation_catalogue_digest(mutations),
        "categories": category_counts(mutations),
        "operators": operator_counts(mutations),
        "operator_count": len(operator_catalog()),
        "mutation_ids": [mutation.mutation_id for mutation in mutations],
        "mutation_digests": [mutation.digest for mutation in mutations],
        "object_paths": object_paths,
        "storage_status": objects.health(),
        "trace_id": trace_id,
        "execution_mode": "deterministic_simulation",
    }


@app.post("/v1/mutations/validate")
def validate(request: MutationValidationRequest) -> dict[str, Any]:
    capsule = _load_capsules([request.capsule_id])[0]
    with traced(
        "mutation.validate",
        {
            "orbital.signal.class": "campaign",
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.mutation.id": request.mutation.mutation_id,
            "orbital.mutation.category": request.mutation.category,
        },
    ):
        trace_id, _ = current_trace_ids()
        try:
            mutated_fixture = validate_mutation(request.mutation, capsule)
        except MutationRejected as exc:
            rejection_id = stable_identifier(
                "reject",
                {
                    "mutation_id": request.mutation.mutation_id,
                    "capsule_id": request.capsule_id,
                    "reason": str(exc),
                },
            )
            store.put(
                rejection_id,
                "mutation_rejection",
                {
                    "rejection_id": rejection_id,
                    "mutation_id": request.mutation.mutation_id,
                    "capsule_id": request.capsule_id,
                    "reason": str(exc),
                    "trace_id": trace_id,
                    "persisted_as_valid_mutation": False,
                },
                request.mutation.created_at,
            )
            mutations_rejected.add(1, {"orbital.mutation.reason": str(exc)[:80]})
            emit_event(
                "mutation.rejected",
                rejection_id=rejection_id,
                mutation_id=request.mutation.mutation_id,
                reason=str(exc),
                trace_id=trace_id,
            )
            raise HTTPException(422, f"mutation rejected: {exc}") from exc
    return {
        "valid": True,
        "reproducible": True,
        "mutation_id": request.mutation.mutation_id,
        "mutated_fixture_digest": sha256_digest(mutated_fixture),
        "trace_id": trace_id,
    }


@app.post("/v1/attacks/adapt")
def adapt(request: AdaptiveRequest) -> dict[str, Any]:
    all_mutations = store.list("replay_mutation", 2000)
    selected_pool = (
        [
            mutation
            for mutation in all_mutations
            if mutation["mutation_id"] in set(request.mutation_ids)
        ]
        if request.mutation_ids
        else all_mutations
    )
    ranked = sorted(
        selected_pool, key=lambda value: (value["fitness"], value["generation"]), reverse=True
    )
    selected = ranked[: request.top_k]
    return {
        "selected": selected,
        "search": {
            "beam_width": request.beam_width,
            "generations": request.generations,
            "budget": request.beam_width * request.generations * max(1, len(selected_pool)),
            "stop_reason": "top_k_valid_attacks_selected",
        },
    }
