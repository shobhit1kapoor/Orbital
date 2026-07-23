from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from celery import Celery
from celery.signals import worker_process_init
from opentelemetry import metrics, trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    set_span_in_context,
)
from orbital_semconv import configure_telemetry, current_trace_ids, emit_event, traced
from orbital_shared.campaigns import digest_suffix, stable_identifier, versioned_path
from orbital_shared.causal import (
    aggregate_counterfactuals,
    minimize_hero_context,
    regression_capsule_payload,
    run_counterfactual,
    write_regression_capsule,
)
from orbital_shared.database import (
    CausalAnalysisRecord,
    CausalBranchRecord,
    MinimizationAttemptRecord,
    MinimizationRunRecord,
    ObjectStore,
)
from orbital_shared.models import sha256_digest, utcnow
from orbital_shared.object_storage import IntegrityError, VersionedObjectStorage
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

configure_telemetry("orbital-causal-worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL.rsplit("/", 1)[0] + "/1")
app = Celery("orbital-causal", broker=REDIS_URL, backend=RESULT_BACKEND)
app.conf.update(
    task_default_queue="causal",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
    task_time_limit=180,
    task_soft_time_limit=170,
)

store = ObjectStore()
objects = VersionedObjectStorage()
meter = metrics.get_meter("orbital-causal-worker")
branch_executions = meter.create_counter("orbital.causal.branches.executed")
branch_duration = meter.create_histogram("orbital.causal.branch.duration", unit="ms")
causal_unknown = meter.create_counter("orbital.causal.unknown")
minimization_attempts = meter.create_counter("orbital.causal.minimization.attempts")
minimization_duration = meter.create_histogram(
    "orbital.causal.minimization.duration", unit="ms"
)


@worker_process_init.connect
def reset_inherited_database_connections(**_: Any) -> None:
    store.engine.dispose(close=False)
    objects.database.engine.dispose(close=False)


def _trace_context(trace_id: str, value: str):
    span_seed = int(digest_suffix(sha256_digest(["parent", value]))[:16], 16) or 1
    context = SpanContext(
        trace_id=int(trace_id, 16),
        span_id=span_seed,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(context))


@app.task(
    bind=True,
    name="orbital.causal.execute_branch",
    max_retries=3,
    default_retry_delay=1,
    autoretry_for=(SQLAlchemyError, IntegrityError),
    retry_backoff=True,
    retry_jitter=False,
)
def execute_branch(self, branch_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    with Session(store.engine) as session:
        branch = session.scalar(
            select(CausalBranchRecord)
            .where(CausalBranchRecord.branch_id == branch_id)
            .with_for_update()
        )
        if not branch:
            return {"branch_id": branch_id, "status": "MISSING"}
        if branch.status == "COMPLETED":
            branch.delivery_count += 1
            session.commit()
            return {
                "branch_id": branch_id,
                "status": "COMPLETED",
                "result_digest": branch.result_digest,
                "idempotent_replay": True,
            }
        branch.status = "RUNNING"
        branch.delivery_count += 1
        branch.retries = int(self.request.retries or 0)
        session.commit()
        trace_id = branch.trace_id
        analysis_id = branch.analysis_id
        interventions = branch.interventions
        seed = branch.seed
        parameters = branch.model_parameters

    context = _trace_context(trace_id, branch_id)
    with trace.get_tracer("orbital-causal-worker").start_as_current_span(
        "causal.counterfactual.execute",
        context=context,
        attributes={
            "orbital.causal.analysis.id": analysis_id,
            "orbital.causal.branch.id": branch_id,
            "orbital.causal.interventions": ",".join(interventions) or "baseline",
            "orbital.causal.seed": seed,
            "orbital.execution.mode": "counterfactual",
            "orbital.signal.class": "causal",
        },
    ):
        actual_trace_id, _ = current_trace_ids()
        result = run_counterfactual(interventions, seed, parameters)
        payload = result.model_dump(mode="json") | {
            "analysis_id": analysis_id,
            "branch_id": branch_id,
            "trace_id": actual_trace_id,
        }
        digest = sha256_digest(payload)
        path = versioned_path(
            "causal-branches", branch_id, digest, "result.json"
        )
        stored = objects.put_json(path, "causal_branch", analysis_id, payload)
        with Session(store.engine) as session:
            branch = session.get(CausalBranchRecord, branch_id)
            if branch.status != "COMPLETED":
                branch.status = "COMPLETED"
                branch.result_payload = payload
                branch.result_digest = digest
                branch.object_path = path
                branch.checksum = stored["checksum"]
                branch.completed_at = utcnow()
                analysis = session.get(CausalAnalysisRecord, analysis_id)
                analysis.status = "RUNNING"
                analysis.completed_branches = int(
                    session.scalar(
                        select(func.count())
                        .select_from(CausalBranchRecord)
                        .where(
                            CausalBranchRecord.analysis_id == analysis_id,
                            CausalBranchRecord.status == "COMPLETED",
                        )
                    )
                    or 0
                )
                session.commit()
        branch_executions.add(
            1,
            {
                "orbital.causal.branch.kind": (
                    "baseline"
                    if not interventions
                    else "single"
                    if len(interventions) == 1
                    else "pairwise"
                )
            },
        )
        branch_duration.record((time.perf_counter() - started) * 1000)
        emit_event(
            "causal.branch.completed",
            analysis_id=analysis_id,
            branch_id=branch_id,
            trace_id=actual_trace_id,
            result_digest=digest,
        )
        return {
            "branch_id": branch_id,
            "status": "COMPLETED",
            "result_digest": digest,
            "trace_id": actual_trace_id,
            "object_path": path,
        }


@app.task(name="orbital.causal.complete_analysis")
def complete_analysis(
    chord_results: list[dict[str, Any]], analysis_id: str
) -> dict[str, Any]:
    with traced(
        "causal.analysis.complete",
        {
            "orbital.causal.analysis.id": analysis_id,
            "orbital.signal.class": "causal",
            "orbital.execution.mode": "counterfactual",
        },
    ):
        trace_id, _ = current_trace_ids()
        with Session(store.engine) as session:
            analysis = session.get(CausalAnalysisRecord, analysis_id)
            if not analysis:
                return {"analysis_id": analysis_id, "status": "MISSING"}
            branches = list(
                session.scalars(
                    select(CausalBranchRecord)
                    .where(CausalBranchRecord.analysis_id == analysis_id)
                    .order_by(
                        CausalBranchRecord.intervention_digest,
                        CausalBranchRecord.repeat_index,
                    )
                ).all()
            )
            results = [
                item.result_payload
                for item in branches
                if item.status == "COMPLETED" and item.result_payload
            ]
            finding = aggregate_counterfactuals(
                results,
                repeat_count=int(analysis.config["repeat_count"]),
                shapley_samples=int(analysis.config["shapley_samples"]),
                bootstrap_samples=int(analysis.config["bootstrap_samples"]),
                seed=int(analysis.config["seed"]),
            )
            payload = finding.model_dump(mode="json") | {
                "analysis_id": analysis_id,
                "finding_id": stable_identifier("finding", analysis_id),
                "source_evidence": analysis.evidence,
                "branch_count": len(branches),
                "completed_branch_count": len(results),
                "branch_trace_ids": [
                    item.result_payload["trace_id"]
                    for item in branches
                    if item.result_payload
                ],
                "completion_trace_id": trace_id,
                "chord_results": len(chord_results),
            }
            digest = sha256_digest(payload)
            path = versioned_path(
                "causal-findings", analysis_id, digest, "finding.json"
            )
            stored = objects.put_json(path, "causal_finding", analysis_id, payload)
            analysis.status = "COMPLETED"
            analysis.verdict = finding.verdict
            analysis.completed_branches = len(results)
            analysis.result_payload = payload
            analysis.finding_digest = digest
            analysis.object_path = path
            analysis.checksum = stored["checksum"]
            analysis.completed_at = utcnow()
            session.commit()
        store.put(
            payload["finding_id"], "causal_finding", payload, utcnow()
        )
        if finding.verdict == "UNKNOWN":
            causal_unknown.add(1)
        emit_event(
            "causal.analysis.completed",
            analysis_id=analysis_id,
            verdict=finding.verdict,
            earliest_commitment_point=finding.earliest_commitment_point,
            trace_id=trace_id,
        )
        return {
            "analysis_id": analysis_id,
            "status": "COMPLETED",
            "verdict": finding.verdict,
            "finding_digest": digest,
            "object_path": path,
        }


@app.task(
    bind=True,
    name="orbital.causal.minimize_hero",
    max_retries=2,
    default_retry_delay=1,
    autoretry_for=(SQLAlchemyError, IntegrityError),
    retry_backoff=True,
    retry_jitter=False,
)
def minimize_hero(self, minimization_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    with Session(store.engine) as session:
        run = session.scalar(
            select(MinimizationRunRecord)
            .where(MinimizationRunRecord.minimization_id == minimization_id)
            .with_for_update()
        )
        if not run:
            return {"minimization_id": minimization_id, "status": "MISSING"}
        if run.status in {"COMPLETED", "LIMITATION"}:
            run.delivery_count += 1
            session.commit()
            return {
                "minimization_id": minimization_id,
                "status": run.status,
                "result_digest": run.result_digest,
                "idempotent_replay": True,
            }
        analysis = session.get(CausalAnalysisRecord, run.analysis_id)
        if not analysis or analysis.verdict != "CONFIRMED":
            run.status = "LIMITATION"
            run.verdict = "UNKNOWN"
            run.result_payload = {
                "reason": "confirmed causal evidence is unavailable"
            }
            run.completed_at = utcnow()
            session.commit()
            return {
                "minimization_id": minimization_id,
                "status": "LIMITATION",
                "verdict": "UNKNOWN",
            }
        run.status = "RUNNING"
        run.delivery_count += 1
        session.commit()
        analysis_id = run.analysis_id
        trace_id = run.trace_id
        timebox_seconds = run.timebox_seconds

    context = _trace_context(trace_id, minimization_id)
    with trace.get_tracer("orbital-causal-worker").start_as_current_span(
        "causal.hero_minimization.execute",
        context=context,
        attributes={
            "orbital.causal.analysis.id": analysis_id,
            "orbital.causal.minimization.id": minimization_id,
            "orbital.causal.timebox_seconds": timebox_seconds,
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.signal.class": "causal",
        },
    ):
        actual_trace_id, _ = current_trace_ids()
        minimized = minimize_hero_context(timebox_seconds=timebox_seconds)
        for attempt in minimized["attempts"]:
            with traced(
                "causal.hero_minimization.attempt",
                {
                    "orbital.causal.minimization.id": minimization_id,
                    "orbital.causal.minimization.sequence": attempt["sequence"],
                    "orbital.causal.minimization.category": attempt["category"],
                    "orbital.causal.failure_preserved": attempt[
                        "failure_preserved"
                    ],
                    "orbital.signal.class": "causal",
                },
            ):
                pass
        attempts_digest = sha256_digest(minimized["attempts"])
        attempts_path = versioned_path(
            "minimization-attempts",
            minimization_id,
            attempts_digest,
            "attempts.json",
        )
        objects.put_json(
            attempts_path,
            "minimization_attempts",
            minimization_id,
            minimized["attempts"],
        )
        regression_payload: dict[str, Any] | None = None
        regression_path: Path | None = None
        regression_object_path: str | None = None
        if minimized["status"] == "COMPLETED":
            regression_payload = regression_capsule_payload(
                analysis_id, minimized
            )
            regression_path = write_regression_capsule(
                Path("/workspace/missions/regressions"),
                regression_payload,
            )
            regression_object_path = versioned_path(
                "minimized-regressions",
                regression_payload["capsule_id"],
                regression_payload["digest"],
                "capsule.json",
            )
            objects.put_json(
                regression_object_path,
                "minimized_regression",
                regression_payload["capsule_id"],
                regression_payload,
            )
        result_payload = {
            "schema_version": "orbital.hero-minimization/v1",
            "minimization_id": minimization_id,
            "analysis_id": analysis_id,
            "status": minimized["status"],
            "verdict": (
                "CONFIRMED"
                if minimized["status"] == "COMPLETED"
                else "UNKNOWN"
            ),
            "reason": minimized["reason"],
            "failure_signature": minimized.get("failure_signature"),
            "original_size": minimized.get("original_size"),
            "minimized_size": minimized.get("minimized_size"),
            "retained_causal_factors": minimized.get(
                "retained_causal_factors", []
            ),
            "attempt_count": len(minimized["attempts"]),
            "attempts_digest": attempts_digest,
            "attempts_object_path": attempts_path,
            "regression_capsule": regression_payload,
            "regression_object_path": regression_object_path,
            "trace_id": actual_trace_id,
            "timebox_seconds": timebox_seconds,
            "duration_seconds": minimized.get("duration_seconds"),
            "execution_mode": "deterministic_simulation",
        }
        result_digest = sha256_digest(result_payload)
        result_path = versioned_path(
            "hero-minimizations",
            minimization_id,
            result_digest,
            "result.json",
        )
        stored = objects.put_json(
            result_path,
            "hero_minimization",
            minimization_id,
            result_payload,
        )
        with Session(store.engine) as session:
            run = session.get(MinimizationRunRecord, minimization_id)
            for attempt in minimized["attempts"]:
                if not session.get(
                    MinimizationAttemptRecord, attempt["attempt_id"]
                ):
                    session.add(
                        MinimizationAttemptRecord(
                            attempt_id=attempt["attempt_id"],
                            minimization_id=minimization_id,
                            sequence=attempt["sequence"],
                            category=attempt["category"],
                            removed_ids=attempt["removed_ids"],
                            candidate_size=attempt["candidate_size"],
                            failure_preserved=attempt["failure_preserved"],
                            result_signature=attempt["result_signature"],
                            trace_id=actual_trace_id,
                            created_at=utcnow(),
                        )
                    )
            run.status = minimized["status"]
            run.verdict = result_payload["verdict"]
            run.result_payload = result_payload
            run.result_digest = result_digest
            run.object_path = result_path
            run.checksum = stored["checksum"]
            run.regression_path = (
                str(regression_path) if regression_path else None
            )
            run.completed_at = utcnow()
            session.commit()
        if regression_payload:
            store.put(
                regression_payload["capsule_id"],
                "regression_capsule",
                regression_payload,
                utcnow(),
            )
        minimization_attempts.add(len(minimized["attempts"]))
        minimization_duration.record((time.perf_counter() - started) * 1000)
        emit_event(
            "causal.hero_minimization.completed",
            minimization_id=minimization_id,
            status=minimized["status"],
            original_size=minimized.get("original_size"),
            minimized_size=minimized.get("minimized_size"),
            trace_id=actual_trace_id,
        )
        return {
            "minimization_id": minimization_id,
            "status": minimized["status"],
            "verdict": result_payload["verdict"],
            "result_digest": result_digest,
            "object_path": result_path,
            "regression_path": str(regression_path) if regression_path else None,
        }
