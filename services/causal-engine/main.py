from __future__ import annotations

import os
from typing import Any

from celery import Celery, chord, group
from fastapi import HTTPException
from opentelemetry import metrics
from orbital_semconv import current_trace_ids, emit_event, traced
from orbital_shared.api import create_service
from orbital_shared.campaigns import (
    deterministic_trace_id,
    stable_identifier,
)
from orbital_shared.causal import (
    FACTORS,
    MAX_REPEATS,
    MAX_SHAPLEY_SAMPLES,
    MAX_TIMEBOX_SECONDS,
    intervention_sets,
)
from orbital_shared.database import (
    AdaptiveBranchRecord,
    CausalAnalysisRecord,
    CausalBranchRecord,
    MinimizationAttemptRecord,
    MinimizationRunRecord,
    MutationRecord,
    ObjectStore,
    RangeCampaignRecord,
    RangeScoreRecord,
)
from orbital_shared.models import sha256_digest, utcnow
from orbital_shared.object_storage import IntegrityError, VersionedObjectStorage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

app = create_service("ORBITAL Σ FORK Causal Engine", "orbital-causal-engine")
store = ObjectStore()
objects = VersionedObjectStorage()
meter = metrics.get_meter("orbital-causal-engine")
analyses_created = meter.create_counter("orbital.causal.analyses.created")
branches_queued = meter.create_counter("orbital.causal.branches.queued")
unknown_results = meter.create_counter("orbital.causal.unknown")
minimizations_created = meter.create_counter("orbital.causal.minimizations.created")


class ModelParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_identifier: str = "qwen3:8b"
    temperature: int = Field(default=0, ge=0, le=0)
    context_window: int = Field(default=8192, ge=8192, le=8192)
    maximum_output_tokens: int = Field(default=1024, ge=1024, le=1024)
    execution_mode: str = Field(
        default="deterministic_simulation",
        pattern="^deterministic_simulation$",
    )


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_mutation_id: str | None = None
    replay_run_id: str | None = None
    repeat_count: int = Field(default=16, ge=8, le=MAX_REPEATS)
    shapley_samples: int = Field(default=64, ge=1, le=MAX_SHAPLEY_SAMPLES)
    bootstrap_samples: int = Field(default=500, ge=100, le=2_000)
    seed: int = 20260723
    model_parameters: ModelParameters = Field(default_factory=ModelParameters)


class MinimizeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    analysis_id: str | None = None
    replay_run_id: str | None = None
    timebox_seconds: int = Field(
        default=MAX_TIMEBOX_SECONDS, ge=1, le=MAX_TIMEBOX_SECONDS
    )


def _celery() -> Celery:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return Celery(
        "orbital-causal-client",
        broker=redis_url,
        backend=os.getenv(
            "CELERY_RESULT_BACKEND", redis_url.rsplit("/", 1)[0] + "/1"
        ),
    )


def _source_evidence(
    requested_mutation_id: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    with Session(store.engine) as session:
        query = (
            select(RangeScoreRecord)
            .join(
                RangeCampaignRecord,
                RangeCampaignRecord.campaign_id == RangeScoreRecord.campaign_id,
            )
            .where(
                RangeScoreRecord.selected.is_(True),
                RangeCampaignRecord.status == "COMPLETED",
            )
            .order_by(RangeScoreRecord.rank)
        )
        if requested_mutation_id:
            query = query.where(
                RangeScoreRecord.mutation_id == requested_mutation_id
            )
        score = session.scalar(query)
        if not score:
            return None, ["selected Phase 4B safety-mutation evidence is missing"]
        campaign = session.get(RangeCampaignRecord, score.campaign_id)
        mutation = session.get(MutationRecord, score.mutation_id)
        branches = list(
            session.scalars(
                select(AdaptiveBranchRecord).where(
                    AdaptiveBranchRecord.campaign_id == score.campaign_id,
                    AdaptiveBranchRecord.seed_mutation_id == score.mutation_id,
                    AdaptiveBranchRecord.status == "COMPLETED",
                )
            ).all()
        )
    failure_branches = [
        item
        for item in branches
        if bool((item.result_payload or {}).get("invariant_violation_observed"))
        and item.object_path
        and item.checksum
        and (item.result_payload or {}).get("trace_id")
    ]
    if not campaign or not mutation:
        reasons.append("source campaign or safety-mutation metadata is missing")
    if not failure_branches:
        reasons.append("no reproducible Phase 4B refund invariant failure exists")
    selection_path = (
        (campaign.result_summary or {}).get("selection_object_path")
        if campaign
        else None
    )
    if not selection_path:
        reasons.append("Phase 4B selection manifest reference is missing")
    if reasons:
        return None, reasons
    source_branch = max(
        failure_branches,
        key=lambda item: (
            float((item.result_payload or {}).get("adaptive_score", 0)),
            item.generation,
            item.branch_id,
        ),
    )
    try:
        selection_manifest = objects.get_json(selection_path)
        branch_result = objects.get_json(
            source_branch.object_path, source_branch.checksum
        )
    except (IntegrityError, Exception) as exc:
        return None, [f"source object evidence unavailable: {type(exc).__name__}"]
    if selection_manifest.get("selection_digest") != campaign.selection_digest:
        return None, ["Phase 4B selection manifest digest is inconsistent"]
    if sha256_digest(branch_result) != source_branch.result_digest:
        return None, ["Phase 4B branch evidence digest is inconsistent"]
    return {
        "source_campaign_id": campaign.campaign_id,
        "source_mutation_id": mutation.mutation_id,
        "source_mutation_digest": mutation.mutation_digest,
        "source_branch_id": source_branch.branch_id,
        "source_branch_digest": source_branch.result_digest,
        "source_trace_id": branch_result["trace_id"],
        "source_object_path": source_branch.object_path,
        "selection_digest": campaign.selection_digest,
        "selection_object_path": selection_path,
        "failure": "refund_declaration_authorization_mismatch",
        "failure_signature": branch_result.get("result_digest"),
        "local_fixture": True,
    }, []


def _analysis_payload(
    session: Session, analysis: CausalAnalysisRecord
) -> dict[str, Any]:
    counts = dict(
        session.execute(
            select(CausalBranchRecord.status, func.count())
            .where(CausalBranchRecord.analysis_id == analysis.analysis_id)
            .group_by(CausalBranchRecord.status)
        ).all()
    )
    return {
        "analysis_id": analysis.analysis_id,
        "status": analysis.status,
        "verdict": analysis.verdict,
        "source_campaign_id": analysis.source_campaign_id,
        "source_mutation_id": analysis.source_mutation_id,
        "source_branch_id": analysis.source_branch_id,
        "source_trace_id": analysis.source_trace_id,
        "expected_branches": analysis.expected_branches,
        "completed_branches": analysis.completed_branches,
        "branch_counts": counts,
        "config": analysis.config,
        "evidence": analysis.evidence,
        "result": analysis.result_payload,
        "finding_digest": analysis.finding_digest,
        "object_path": analysis.object_path,
        "checksum": analysis.checksum,
        "trace_id": analysis.trace_id,
    }


@app.post("/v1/causal/analyze", status_code=202)
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    with traced(
        "causal.analysis.create",
        {
            "orbital.signal.class": "causal",
            "orbital.execution.mode": "counterfactual",
            "orbital.causal.repeat_count": request.repeat_count,
            "orbital.causal.shapley_samples": request.shapley_samples,
        },
    ):
        trace_id, _ = current_trace_ids()
        evidence, reasons = _source_evidence(request.source_mutation_id)
        config = {
            "factors": list(FACTORS),
            "repeat_count": request.repeat_count,
            "shapley_samples": request.shapley_samples,
            "bootstrap_samples": request.bootstrap_samples,
            "seed": request.seed,
            "model_parameters": request.model_parameters.model_dump(mode="json"),
        }
        submission = {
            "source": evidence
            or {"requested_mutation_id": request.source_mutation_id, "reasons": reasons},
            "config": config,
            "version": "phase4c.causal.v1",
        }
        submission_digest = sha256_digest(submission)
        analysis_id = stable_identifier("analysis", submission_digest)
        now = utcnow()
        with Session(store.engine) as session:
            existing = session.get(CausalAnalysisRecord, analysis_id)
            if existing:
                pending_ids = list(
                    session.scalars(
                        select(CausalBranchRecord.branch_id)
                        .where(
                            CausalBranchRecord.analysis_id == analysis_id,
                            CausalBranchRecord.status != "COMPLETED",
                        )
                        .order_by(CausalBranchRecord.branch_id)
                    ).all()
                )
                if pending_ids:
                    existing.status = "QUEUED"
                    session.commit()
                    client = _celery()
                    header = group(
                        client.signature(
                            "orbital.causal.execute_branch",
                            args=[branch_id],
                            immutable=True,
                            queue="causal",
                        )
                        for branch_id in pending_ids
                    )
                    callback = client.signature(
                        "orbital.causal.complete_analysis",
                        args=[analysis_id],
                        queue="causal",
                    )
                    recovery = chord(header)(callback)
                    recovery_id = str(recovery.id)
                else:
                    recovery_id = None
                return _analysis_payload(session, existing) | {
                    "duplicate_submission": True,
                    "recovery_dispatched": bool(pending_ids),
                    "recovered_branches": len(pending_ids),
                    "recovery_chord_id": recovery_id,
                }
            if not evidence:
                result = {
                    "schema_version": "orbital.causal.finding/v1",
                    "verdict": "UNKNOWN",
                    "reason": "; ".join(reasons),
                    "evidence_complete": False,
                    "attribution": [],
                    "single_effects": [],
                    "pairwise_effects": [],
                }
                analysis = CausalAnalysisRecord(
                    analysis_id=analysis_id,
                    submission_digest=submission_digest,
                    status="COMPLETED",
                    verdict="UNKNOWN",
                    expected_branches=0,
                    completed_branches=0,
                    config=config,
                    evidence={"reasons": reasons},
                    result_payload=result,
                    trace_id=trace_id,
                    created_at=now,
                    completed_at=now,
                )
                session.add(analysis)
                session.commit()
                unknown_results.add(1)
                emit_event(
                    "causal.analysis.unknown",
                    analysis_id=analysis_id,
                    reasons=reasons,
                    trace_id=trace_id,
                )
                return _analysis_payload(session, analysis) | {
                    "duplicate_submission": False
                }

            combinations = intervention_sets()
            expected = len(combinations) * request.repeat_count
            analysis = CausalAnalysisRecord(
                analysis_id=analysis_id,
                submission_digest=submission_digest,
                source_campaign_id=evidence["source_campaign_id"],
                source_mutation_id=evidence["source_mutation_id"],
                source_branch_id=evidence["source_branch_id"],
                source_trace_id=evidence["source_trace_id"],
                status="QUEUED",
                verdict="UNKNOWN",
                expected_branches=expected,
                completed_branches=0,
                config=config,
                evidence=evidence,
                result_payload={},
                trace_id=trace_id,
                created_at=now,
            )
            session.add(analysis)
            session.flush()
            branch_ids: list[str] = []
            for interventions in combinations:
                intervention_digest = sha256_digest(list(interventions))
                kind = (
                    "baseline"
                    if not interventions
                    else "single"
                    if len(interventions) == 1
                    else "pairwise"
                )
                for repeat in range(request.repeat_count):
                    branch_seed = request.seed + repeat
                    branch_id = stable_identifier(
                        "causebranch",
                        [
                            analysis_id,
                            intervention_digest,
                            repeat,
                            branch_seed,
                        ],
                    )
                    branch_ids.append(branch_id)
                    session.add(
                        CausalBranchRecord(
                            branch_id=branch_id,
                            analysis_id=analysis_id,
                            intervention_digest=intervention_digest,
                            interventions=list(interventions),
                            branch_kind=kind,
                            repeat_index=repeat,
                            seed=branch_seed,
                            model_parameters=request.model_parameters.model_dump(
                                mode="json"
                            ),
                            trace_id=deterministic_trace_id(branch_id),
                            status="QUEUED",
                            delivery_count=0,
                            retries=0,
                            created_at=now,
                        )
                    )
            session.commit()

        client = _celery()
        header = group(
            client.signature(
                "orbital.causal.execute_branch",
                args=[branch_id],
                immutable=True,
                queue="causal",
            )
            for branch_id in branch_ids
        )
        callback = client.signature(
            "orbital.causal.complete_analysis",
            args=[analysis_id],
            queue="causal",
        )
        result = chord(header)(callback)
        analyses_created.add(1)
        branches_queued.add(expected)
        emit_event(
            "causal.analysis.dispatched",
            analysis_id=analysis_id,
            branches=expected,
            chord_id=result.id,
            trace_id=trace_id,
        )
    return {
        "analysis_id": analysis_id,
        "status": "QUEUED",
        "verdict": "UNKNOWN",
        "expected_branches": expected,
        "source_mutation_id": evidence["source_mutation_id"],
        "source_branch_id": evidence["source_branch_id"],
        "source_trace_id": evidence["source_trace_id"],
        "trace_id": trace_id,
        "celery_chord_id": str(result.id),
        "duplicate_submission": False,
    }


@app.get("/v1/causal/analyses/{analysis_id}")
def analysis_status(analysis_id: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        analysis = session.get(CausalAnalysisRecord, analysis_id)
        if not analysis:
            raise HTTPException(404, "causal analysis not found")
        return _analysis_payload(session, analysis)


@app.post(
    "/v1/causal/analyses/{analysis_id}/branches/{branch_id}/redeliver",
    status_code=202,
)
def redeliver_branch(analysis_id: str, branch_id: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        branch = session.get(CausalBranchRecord, branch_id)
        if not branch or branch.analysis_id != analysis_id:
            raise HTTPException(404, "causal branch not found")
        digest = branch.result_digest
    task = _celery().send_task(
        "orbital.causal.execute_branch", args=[branch_id], queue="causal"
    )
    return {
        "branch_id": branch_id,
        "task_id": str(task.id),
        "original_result_digest": digest,
        "expected_idempotent": digest is not None,
    }


@app.post("/v1/causal/minimize", status_code=202)
def minimize(request: MinimizeRequest) -> dict[str, Any]:
    with Session(store.engine) as session:
        if request.analysis_id:
            analysis = session.get(CausalAnalysisRecord, request.analysis_id)
        else:
            analysis = session.scalar(
                select(CausalAnalysisRecord)
                .where(
                    CausalAnalysisRecord.status == "COMPLETED",
                    CausalAnalysisRecord.verdict == "CONFIRMED",
                )
                .order_by(CausalAnalysisRecord.completed_at.desc())
            )
        if not analysis:
            raise HTTPException(409, "confirmed primary causal analysis is unavailable")
        analysis_id = analysis.analysis_id
        minimization_id = stable_identifier(
            "minhero",
            [
                analysis_id,
                request.timebox_seconds,
                "phase4c.hero-minimizer.v1",
            ],
        )
        existing = session.get(MinimizationRunRecord, minimization_id)
        if existing:
            return {
                "minimization_id": minimization_id,
                "analysis_id": analysis_id,
                "status": existing.status,
                "verdict": existing.verdict,
                "result": existing.result_payload,
                "trace_id": existing.trace_id,
                "duplicate_submission": True,
            }
        now = utcnow()
        run = MinimizationRunRecord(
            minimization_id=minimization_id,
            analysis_id=analysis_id,
            status="QUEUED",
            verdict="UNKNOWN",
            timebox_seconds=request.timebox_seconds,
            trace_id=deterministic_trace_id(minimization_id),
            delivery_count=0,
            source_digest=analysis.finding_digest or sha256_digest(analysis.evidence),
            result_payload={},
            created_at=now,
        )
        session.add(run)
        session.commit()
        run_trace_id = run.trace_id
    task = _celery().send_task(
        "orbital.causal.minimize_hero",
        args=[minimization_id],
        queue="causal",
    )
    minimizations_created.add(1)
    return {
        "minimization_id": minimization_id,
        "analysis_id": analysis_id,
        "status": "QUEUED",
        "verdict": "UNKNOWN",
        "timebox_seconds": request.timebox_seconds,
        "trace_id": run_trace_id,
        "celery_task_id": str(task.id),
        "duplicate_submission": False,
    }


@app.get("/v1/causal/minimizations/{minimization_id}")
def minimization_status(minimization_id: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        run = session.get(MinimizationRunRecord, minimization_id)
        if not run:
            raise HTTPException(404, "hero minimization not found")
        attempts = int(
            session.scalar(
                select(func.count())
                .select_from(MinimizationAttemptRecord)
                .where(
                    MinimizationAttemptRecord.minimization_id == minimization_id
                )
            )
            or 0
        )
        return {
            "minimization_id": run.minimization_id,
            "analysis_id": run.analysis_id,
            "status": run.status,
            "verdict": run.verdict,
            "timebox_seconds": run.timebox_seconds,
            "attempt_count": attempts,
            "result": run.result_payload,
            "result_digest": run.result_digest,
            "object_path": run.object_path,
            "checksum": run.checksum,
            "regression_path": run.regression_path,
            "trace_id": run.trace_id,
            "delivery_count": run.delivery_count,
        }


@app.post(
    "/v1/causal/minimizations/{minimization_id}/redeliver",
    status_code=202,
)
def redeliver_minimization(minimization_id: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        run = session.get(MinimizationRunRecord, minimization_id)
        if not run:
            raise HTTPException(404, "hero minimization not found")
        digest = run.result_digest
    task = _celery().send_task(
        "orbital.causal.minimize_hero",
        args=[minimization_id],
        queue="causal",
    )
    return {
        "minimization_id": minimization_id,
        "task_id": str(task.id),
        "original_result_digest": digest,
        "expected_idempotent": digest is not None,
    }


@app.get("/v1/causal/findings")
def findings() -> list[dict[str, Any]]:
    return store.list("causal_finding", 100)
