from __future__ import annotations

import json
import os
from time import perf_counter
from typing import Any

from celery import Celery, chain, chord, group
from fastapi import HTTPException
from openai import OpenAI
from opentelemetry import metrics
from orbital_semconv import current_trace_ids, emit_event, traced
from orbital_shared.api import create_service
from orbital_shared.campaigns import (
    deterministic_trace_id,
    stable_identifier,
    versioned_path,
)
from orbital_shared.database import (
    AdaptiveBranchRecord,
    CapsuleRecord,
    MutationRecord,
    ObjectStore,
    RangeCampaignRecord,
    RangeScoreRecord,
)
from orbital_shared.models import MissionCapsule, ReplayMutation, sha256_digest, utcnow
from orbital_shared.object_storage import IntegrityError, VersionedObjectStorage
from orbital_shared.range_evaluation import (
    BEAM_WIDTH,
    MAX_GENERATIONS,
    SCORING_VERSION,
    SELECTION_SIZE,
    AdaptiveProposal,
    branch_identifier,
    fallback_proposals,
    rank_mutations,
    selection_digest,
)
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
range_mutations_scored = meter.create_counter(
    "orbital.range.safety_mutations.scored"
)
range_test_cases_selected = meter.create_counter(
    "orbital.range.test_cases.selected"
)
range_search_budget = meter.create_histogram(
    "orbital.range.search.budget", unit="{branch}"
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
    top_k: int = Field(default=SELECTION_SIZE, ge=SELECTION_SIZE, le=SELECTION_SIZE)
    beam_width: int = Field(default=BEAM_WIDTH, ge=BEAM_WIDTH, le=BEAM_WIDTH)
    generations: int = Field(
        default=MAX_GENERATIONS, ge=MAX_GENERATIONS, le=MAX_GENERATIONS
    )
    force_deterministic_fallback: bool = False


def _celery() -> Celery:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return Celery(
        "orbital-range-client",
        broker=redis_url,
        backend=os.getenv(
            "CELERY_RESULT_BACKEND", redis_url.rsplit("/", 1)[0] + "/1"
        ),
    )


def _ollama_proposals(generations: int) -> tuple[list[AdaptiveProposal], str]:
    if os.getenv("RANGE_FORCE_DETERMINISTIC_FALLBACK", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        raise RuntimeError("deterministic fallback forced by configuration")
    client = OpenAI(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1"),
        api_key="ollama-local",
        timeout=3.0,
        max_retries=0,
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["proposals"],
        "properties": {
            "proposals": {
                "type": "array",
                "minItems": generations * BEAM_WIDTH,
                "maxItems": generations * BEAM_WIDTH,
                "items": AdaptiveProposal.model_json_schema(),
            }
        },
    }
    response = client.chat.completions.create(
        model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        temperature=0,
        max_tokens=1024,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "orbital_range_proposals", "schema": schema},
        },
        messages=[
            {
                "role": "system",
                "content": (
                    "Return only schema-valid synthetic local test transformations. "
                    "Create four proposals per generation in generation then beam "
                    "order. Do not target external systems."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Create {generations * BEAM_WIDTH} bounded RANGE proposals "
                    f"for {generations} generations."
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    proposals = [AdaptiveProposal.model_validate(item) for item in payload["proposals"]]
    expected = [
        (generation, beam)
        for generation in range(1, generations + 1)
        for beam in range(BEAM_WIDTH)
    ]
    if [(item.generation, item.beam_index) for item in proposals] != expected:
        raise ValueError("Ollama proposals are not in complete generation/beam order")
    return proposals, "ollama_structured"


def _proposal_catalogue(
    generations: int, force_fallback: bool
) -> tuple[list[AdaptiveProposal], str, str | None]:
    if not force_fallback:
        try:
            return (*_ollama_proposals(generations), None)
        except Exception as exc:
            fallback_reason = type(exc).__name__
    else:
        fallback_reason = "request_forced"
    proposals = [
        proposal
        for generation in range(1, generations + 1)
        for proposal in fallback_proposals(generation)
    ]
    return proposals, "deterministic_fallback", fallback_reason


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
    with Session(store.engine) as session:
        query = select(MutationRecord).order_by(MutationRecord.sequence)
        records = list(session.scalars(query).all())
    if request.mutation_ids:
        requested_ids = set(request.mutation_ids)
        records = [item for item in records if item.mutation_id in requested_ids]
        missing = sorted(requested_ids - {item.mutation_id for item in records})
        if missing:
            raise HTTPException(422, f"mutations are not persisted: {missing[:5]}")
    if len(records) != 880:
        raise HTTPException(
            409, f"Phase 4B requires the complete 880-mutation catalogue; found {len(records)}"
        )
    try:
        mutations = [ReplayMutation.model_validate(item.payload) for item in records]
    except ValueError as exc:
        raise HTTPException(422, f"invalid persisted mutation schema: {exc}") from exc

    catalogue_digest = mutation_catalogue_digest(mutations)
    with traced(
        "range.selection.score",
        {
            "orbital.signal.class": "campaign",
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.range.scoring.version": SCORING_VERSION,
            "orbital.range.catalogue.count": len(mutations),
            "orbital.range.selection.count": request.top_k,
            "orbital.risk.class": "high",
        },
    ):
        trace_id, _ = current_trace_ids()
        try:
            scores, selected = rank_mutations(
                mutations, catalogue_digest, request.top_k
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        selected_digest = selection_digest(selected)
        proposal_catalogue, proposal_source, fallback_reason = _proposal_catalogue(
            request.generations, request.force_deterministic_fallback
        )
        search_budget = len(selected) * request.beam_width * request.generations
        range_mutations_scored.add(len(scores))
        range_test_cases_selected.add(len(selected))
        range_search_budget.record(search_budget)
        submission = {
            "catalogue_digest": catalogue_digest,
            "selection_digest": selected_digest,
            "beam_width": request.beam_width,
            "generations": request.generations,
            "search_budget": search_budget,
            "proposal_source": proposal_source,
            "proposal_catalogue_digest": sha256_digest(
                [item.model_dump(mode="json") for item in proposal_catalogue]
            ),
        }
        submission_digest = sha256_digest(submission)
        campaign_id = stable_identifier("range", submission_digest)
        selection_payload = {
            "schema_version": "orbital.range.selection/v1",
            "campaign_id": campaign_id,
            "catalogue_digest": catalogue_digest,
            "selection_digest": selected_digest,
            "scoring_version": SCORING_VERSION,
            "selected": [
                {
                    "rank": rank,
                    **item.model_dump(mode="json"),
                }
                for rank, item in enumerate(selected, start=1)
            ],
            "execution_mode": "deterministic_simulation",
        }
        selection_path = versioned_path(
            "range-selections",
            campaign_id,
            selected_digest,
            "selection.json",
        )
        selection_object = objects.put_json(
            selection_path,
            "range_selection",
            campaign_id,
            selection_payload,
        )
        now = utcnow()
        with Session(store.engine) as session:
            existing = session.get(RangeCampaignRecord, campaign_id)
            if existing:
                existing.result_summary = (existing.result_summary or {}) | {
                    "selection_object_path": selection_path,
                    "selection_object_checksum": selection_object["checksum"],
                }
                pending_ids = list(
                    session.scalars(
                        select(AdaptiveBranchRecord.branch_id)
                        .where(
                            AdaptiveBranchRecord.campaign_id == campaign_id,
                            AdaptiveBranchRecord.status != "COMPLETED",
                        )
                        .order_by(
                            AdaptiveBranchRecord.generation,
                            AdaptiveBranchRecord.beam_index,
                        )
                    ).all()
                )
                recovered_chord_id: str | None = None
                if pending_ids:
                    existing.status = "QUEUED"
                session.commit()
                if pending_ids:
                    client = _celery()
                    header = group(
                        client.signature(
                            "orbital.range.execute_branch",
                            args=[branch_id],
                            immutable=True,
                        )
                        for branch_id in pending_ids
                    )
                    callback = client.signature(
                        "orbital.range.complete_campaign",
                        args=[campaign_id],
                        immutable=True,
                    )
                    recovered_chord_id = str(chord(header)(callback).id)
                return {
                    "campaign_id": existing.campaign_id,
                    "status": existing.status,
                    "duplicate_submission": True,
                    "recovery_dispatched": bool(pending_ids),
                    "recovered_branches": len(pending_ids),
                    "catalogue_digest": existing.catalogue_digest,
                    "selection_digest": existing.selection_digest,
                    "selection_object_path": selection_path,
                    "selected_count": existing.selected_count,
                    "search": {
                        "beam_width": existing.beam_width,
                        "generations": existing.max_generations,
                        "budget": existing.search_budget,
                        "budget_used": existing.budget_used,
                        "proposal_source": existing.proposal_source,
                        "celery_chord_id": recovered_chord_id,
                    },
                    "trace_id": trace_id,
                }
            session.add(
                RangeCampaignRecord(
                    campaign_id=campaign_id,
                    submission_digest=submission_digest,
                    catalogue_digest=catalogue_digest,
                    selection_digest=selected_digest,
                    status="QUEUED",
                    beam_width=request.beam_width,
                    max_generations=request.generations,
                    search_budget=search_budget,
                    budget_used=0,
                    selected_count=len(selected),
                    proposal_source=proposal_source,
                    result_summary={
                        "fallback_reason": fallback_reason,
                        "selection_trace_id": trace_id,
                        "selection_object_path": selection_path,
                        "selection_object_checksum": selection_object["checksum"],
                        "submission": submission,
                    },
                    created_at=now,
                )
            )
            # Explicitly establish the parent row before bulk-inserting 2,160
            # score and branch rows. These models intentionally avoid ORM
            # relationships, so SQLAlchemy cannot infer flush ordering.
            session.flush()
            selected_ids = {item.mutation_id for item in selected}
            ranks = {
                item.mutation_id: rank
                for rank, item in enumerate(selected, start=1)
            }
            for score in scores:
                provenance = score.provenance | {
                    "selection_digest": selected_digest,
                    "rank": ranks.get(score.mutation_id),
                    "selected": score.mutation_id in selected_ids,
                }
                session.add(
                    RangeScoreRecord(
                        mutation_id=score.mutation_id,
                        campaign_id=campaign_id,
                        rank=ranks.get(score.mutation_id),
                        selected=score.mutation_id in selected_ids,
                        total_score=score.total_score,
                        factors=score.factors.model_dump(mode="json"),
                        provenance=provenance,
                        score_digest=score.score_digest,
                        created_at=now,
                    )
                )

            chains = []
            by_generation = {
                generation: [
                    item
                    for item in proposal_catalogue
                    if item.generation == generation
                ]
                for generation in range(1, request.generations + 1)
            }
            for score in selected:
                for beam_index in range(request.beam_width):
                    signatures = []
                    parent_id: str | None = None
                    for generation in range(1, request.generations + 1):
                        proposal = by_generation[generation][beam_index]
                        proposal_payload = proposal.model_dump(mode="json")
                        proposal_digest = sha256_digest(proposal_payload)
                        branch_id = branch_identifier(
                            campaign_id,
                            score.mutation_id,
                            generation,
                            beam_index,
                            proposal_digest,
                        )
                        session.add(
                            AdaptiveBranchRecord(
                                branch_id=branch_id,
                                campaign_id=campaign_id,
                                seed_mutation_id=score.mutation_id,
                                parent_branch_id=parent_id,
                                generation=generation,
                                beam_index=beam_index,
                                trace_id=deterministic_trace_id(branch_id),
                                status="QUEUED",
                                delivery_count=0,
                                proposal=proposal_payload,
                                proposal_digest=proposal_digest,
                                created_at=now,
                            )
                        )
                        signatures.append(
                            _celery().signature(
                                "orbital.range.execute_branch",
                                args=[branch_id],
                                immutable=True,
                            )
                        )
                        parent_id = branch_id
                    chains.append(chain(*signatures))
            session.commit()

        client = _celery()
        callback = client.signature(
            "orbital.range.complete_campaign", args=[campaign_id], immutable=True
        )
        async_result = chord(group(chains))(callback)
        emit_event(
            "range.selection.completed",
            campaign_id=campaign_id,
            scored_count=len(scores),
            selected_count=len(selected),
            selection_digest=selected_digest,
            selection_object_path=selection_path,
            trace_id=trace_id,
        )
        emit_event(
            "range.adaptive.dispatched",
            campaign_id=campaign_id,
            selected_count=len(selected),
            search_budget=search_budget,
            proposal_source=proposal_source,
            trace_id=trace_id,
        )
    return {
        "campaign_id": campaign_id,
        "status": "QUEUED",
        "duplicate_submission": False,
        "catalogue_digest": catalogue_digest,
        "selection_digest": selected_digest,
        "selection_object_path": selection_path,
        "selected_count": len(selected),
        "selected": [
            {
                "rank": rank,
                "mutation_id": item.mutation_id,
                "total_score": item.total_score,
                "factors": item.factors.model_dump(mode="json"),
                "score_digest": item.score_digest,
                "provenance": item.provenance,
            }
            for rank, item in enumerate(selected, start=1)
        ],
        "search": {
            "beam_width": request.beam_width,
            "generations": request.generations,
            "budget": search_budget,
            "budget_used": 0,
            "proposal_source": proposal_source,
            "fallback_reason": fallback_reason,
            "celery_chord_id": str(async_result.id),
        },
        "trace_id": trace_id,
        "execution_mode": "deterministic_simulation",
    }


@app.get("/v1/attacks/adapt/{campaign_id}")
def adaptive_status(campaign_id: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        campaign = session.get(RangeCampaignRecord, campaign_id)
        if not campaign:
            raise HTTPException(404, "adaptive campaign not found")
        selected = list(
            session.scalars(
                select(RangeScoreRecord)
                .where(
                    RangeScoreRecord.campaign_id == campaign_id,
                    RangeScoreRecord.selected.is_(True),
                )
                .order_by(RangeScoreRecord.rank)
            ).all()
        )
        return {
            "campaign_id": campaign.campaign_id,
            "status": campaign.status,
            "catalogue_digest": campaign.catalogue_digest,
            "selection_digest": campaign.selection_digest,
            "selected_count": campaign.selected_count,
            "selected": [
                {
                    "rank": item.rank,
                    "mutation_id": item.mutation_id,
                    "score": item.total_score,
                    "score_digest": item.score_digest,
                    "provenance": item.provenance,
                }
                for item in selected
            ],
            "search": {
                "beam_width": campaign.beam_width,
                "generations": campaign.max_generations,
                "budget": campaign.search_budget,
                "budget_used": campaign.budget_used,
                "proposal_source": campaign.proposal_source,
            },
            "result_summary": campaign.result_summary,
        }


@app.post(
    "/v1/attacks/adapt/{campaign_id}/branches/{branch_id}/redeliver",
    status_code=202,
)
def redeliver_adaptive_branch(
    campaign_id: str, branch_id: str
) -> dict[str, Any]:
    with Session(store.engine) as session:
        branch = session.get(AdaptiveBranchRecord, branch_id)
        if not branch or branch.campaign_id != campaign_id:
            raise HTTPException(404, "adaptive test-case branch not found")
        original_digest = branch.result_digest
    task = _celery().send_task("orbital.range.execute_branch", args=[branch_id])
    return {
        "campaign_id": campaign_id,
        "branch_id": branch_id,
        "task_id": str(task.id),
        "original_result_digest": original_digest,
        "expected_idempotent": original_digest is not None,
    }
