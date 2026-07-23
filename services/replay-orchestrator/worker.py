from __future__ import annotations

import os
import time
from typing import Any

from campaign_runtime import replay_outcome
from celery import Celery, chord, group
from celery.exceptions import MaxRetriesExceededError
from celery.signals import worker_process_init
from opentelemetry import metrics, trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    set_span_in_context,
)
from orbital_semconv import configure_telemetry, current_trace_ids, emit_event, traced
from orbital_shared.campaigns import (
    CampaignRepository,
    digest_suffix,
    signoz_trace_url,
    versioned_path,
)
from orbital_shared.database import (
    AdaptiveBranchRecord,
    CampaignRecord,
    CapsuleRecord,
    MetamorphicCaseRecord,
    MutationRecord,
    RangeCampaignRecord,
    RangeScoreRecord,
    ReplayJobRecord,
)
from orbital_shared.metamorphic import evaluate_invariant
from orbital_shared.models import ReplayMutation, sha256_digest, utcnow
from orbital_shared.object_storage import IntegrityError, VersionedObjectStorage
from orbital_shared.range_evaluation import (
    AdaptiveProposal,
    evaluate_branch,
    score_mutation,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

configure_telemetry("orbital-replay-worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL.rsplit("/", 1)[0] + "/1")
app = Celery("orbital-replay", broker=REDIS_URL, backend=RESULT_BACKEND)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
    task_time_limit=int(os.getenv("REPLAY_TASK_TIME_LIMIT_SECONDS", "60")),
    task_soft_time_limit=int(os.getenv("REPLAY_TASK_SOFT_LIMIT_SECONDS", "55")),
)

repository = CampaignRepository()
objects = VersionedObjectStorage()
meter = metrics.get_meter("orbital-replay-worker")
worker_executions = meter.create_counter("orbital.replay.worker.executions")
worker_retries = meter.create_counter("orbital.replay.worker.retries")
replay_duration = meter.create_histogram("orbital.replay.duration", unit="ms")
queue_delay = meter.create_histogram("orbital.replay.queue.delay", unit="ms")
postgres_failures = meter.create_counter("orbital.postgresql.write.failures")
worker_active = meter.create_up_down_counter("orbital.worker.active")
range_branches = meter.create_counter("orbital.range.adaptive.branches")
range_duration = meter.create_histogram("orbital.range.adaptive.duration", unit="ms")
metamorphic_evaluations = meter.create_counter("orbital.metamorphic.evaluations")
metamorphic_failures = meter.create_counter("orbital.metamorphic.failures")


@worker_process_init.connect
def reset_inherited_database_connections(**_: Any) -> None:
    # Celery's prefork workers must never share psycopg connections or prepared
    # statement state inherited from the parent process.
    repository.engine.dispose(close=False)
    objects.database.engine.dispose(close=False)


def _trace_context(trace_id: str, job_id: str):
    span_seed = int(digest_suffix(sha256_digest(["parent", job_id]))[:16], 16) or 1
    context = SpanContext(
        trace_id=int(trace_id, 16),
        span_id=span_seed,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(context))


def dispatch_campaign(campaign_id: str, job_ids: list[str]) -> str:
    header = group(execute_replay_job.s(job_id) for job_id in job_ids)
    result = chord(header)(complete_campaign.s(campaign_id))
    emit_event(
        "campaign.chord.dispatched",
        campaign_id=campaign_id,
        jobs=len(job_ids),
        chord_id=result.id,
    )
    return str(result.id)


def dispatch_metamorphic_suite(suite_id: str, case_ids: list[str]) -> str:
    header = group(execute_metamorphic_case.s(case_id) for case_id in case_ids)
    result = chord(header)(complete_metamorphic_suite.s(suite_id))
    emit_event(
        "metamorphic.suite.dispatched",
        suite_id=suite_id,
        cases=len(case_ids),
        chord_id=result.id,
    )
    return str(result.id)


def _defer_job(job_id: str, campaign_status: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        job = session.get(ReplayJobRecord, job_id)
        if job and job.status != "COMPLETED":
            job.status = "CANCELLED" if campaign_status == "CANCELLED" else "QUEUED"
            job.updated_at = utcnow()
            repository.add_event(
                session,
                job.campaign_id,
                "job.deferred",
                {
                    "job_id": job_id,
                    "reason": campaign_status,
                    "status": job.status,
                },
            )
            session.commit()
    return {"job_id": job_id, "deferred": True, "reason": campaign_status}


@app.task(
    bind=True,
    name="orbital.replay.execute",
    max_retries=4,
    default_retry_delay=1,
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_jitter=False,
)
def execute_replay_job(self, job_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    now = utcnow()
    with Session(repository.engine) as session:
        job = session.scalar(
            select(ReplayJobRecord).where(ReplayJobRecord.job_id == job_id).with_for_update()
        )
        if not job:
            return {"job_id": job_id, "status": "MISSING"}
        campaign = session.get(CampaignRecord, job.campaign_id)
        if not campaign:
            return {"job_id": job_id, "status": "MISSING_CAMPAIGN"}
        if job.status == "COMPLETED":
            job.delivery_count += 1
            job.updated_at = now
            repository.add_event(
                session,
                campaign.campaign_id,
                "job.duplicate_delivery",
                {
                    "job_id": job.job_id,
                    "result_digest": job.result_digest,
                    "idempotent": True,
                },
            )
            session.commit()
            return {
                "job_id": job.job_id,
                "status": "COMPLETED",
                "result_digest": job.result_digest,
                "idempotent_replay": True,
            }
        if campaign.status in {"PAUSED", "CANCELLED"}:
            campaign_status = campaign.status
            session.commit()
            return _defer_job(job_id, campaign_status)
        job.status = "RUNNING"
        job.delivery_count += 1
        job.started_at = now
        job.updated_at = now
        if campaign.status in {"CREATED", "QUEUED", "PARTIAL", "FAILED"}:
            repository.transition(session, campaign, "RUNNING", "campaign.running")
        queue_delay.record(
            max(0.0, (now - (job.queued_at or job.created_at)).total_seconds() * 1000),
            {"orbital.campaign.id": campaign.campaign_id},
        )
        session.commit()
        campaign_payload = campaign.request_payload
        trace_id = job.trace_id
        campaign_id = campaign.campaign_id
        capsule_id = job.capsule_id
        mutation_id = job.mutation_id
        mission_id = job.mission_id
        replay_id = job.replay_id
        candidate_id = job.candidate_id
        attempt = job.delivery_count

    worker_active.add(1)
    worker_executions.add(1)
    context = _trace_context(trace_id, job_id)
    try:
        with trace.get_tracer("orbital-replay-worker").start_as_current_span(
            "replay.worker.execute",
            context=context,
            attributes={
                "orbital.campaign.id": campaign_id,
                "orbital.replay.job_id": job_id,
                "orbital.replay.id": replay_id,
                "orbital.mission.id": mission_id,
                "orbital.candidate.id": candidate_id,
                "orbital.mutation.id": mutation_id or "nominal",
                "orbital.replay.attempt": attempt,
                "orbital.signal.class": "campaign",
            },
        ) as span:
            actual_trace_id, span_id = current_trace_ids()
            with Session(repository.engine) as session:
                capsule_record = session.get(CapsuleRecord, capsule_id)
                if not capsule_record:
                    raise IntegrityError(f"capsule metadata unavailable: {capsule_id}")
            with traced(
                "capsule.load",
                {
                    "orbital.capsule.id": capsule_id,
                    "orbital.campaign.id": campaign_id,
                },
            ):
                capsule_manifest = objects.get_json(
                    capsule_record.object_path,
                    capsule_record.checksum,
                )
            mutation = repository.object_store.get(mutation_id) if mutation_id else None
            fail_once = job_id in campaign_payload.get("fail_once_job_ids", [])
            failure_marker = f"retry-marker:{job_id}"
            if fail_once and not repository.object_store.get(failure_marker):
                repository.object_store.put(
                    failure_marker,
                    "replay_retry_marker",
                    {"job_id": job_id, "attempt": attempt},
                    utcnow(),
                )
                raise TimeoutError("deterministic first-delivery timeout")
            delay_ms = int(campaign_payload.get("job_delay_ms", 0))
            if delay_ms:
                time.sleep(min(delay_ms, 5_000) / 1000)
            with traced("replay.execute"):
                run = replay_outcome(
                    candidate_id=candidate_id,
                    artifact_digest=campaign_payload["artifact_digest"],
                    capsule_id=capsule_id,
                    mutation_id=mutation_id,
                    mutation=mutation,
                    mode=campaign_payload["mode"],
                    seed=campaign_payload["seed"],
                    mission_id=mission_id,
                    trace_id=actual_trace_id,
                    span_id=span_id,
                    replay_id=replay_id,
                    authority_level=campaign_payload["authority_level"],
                )
            run.trace_url = signoz_trace_url(actual_trace_id)
            result_payload = run.model_dump(mode="json")
            result_payload["capsule_checksum"] = capsule_record.checksum
            result_payload["capsule_digest"] = capsule_manifest["capsule_digest"]
            result_digest = sha256_digest(result_payload)
            branch_path = versioned_path(
                "replay-branches",
                replay_id,
                result_digest,
                "result.json",
            )
            with traced("replay.persist"):
                objects.put_json(
                    branch_path,
                    "replay_branch",
                    campaign_id,
                    result_payload,
                )
                receipt_id = f"replay-effect:{job_id}"
                repository.object_store.put(
                    receipt_id,
                    "replay_effect_receipt",
                    {
                        "receipt_id": receipt_id,
                        "job_id": job_id,
                        "effect": "deterministic_simulation_only",
                        "result_digest": result_digest,
                    },
                    utcnow(),
                )
                repository.object_store.put(
                    replay_id,
                    "replay_run",
                    result_payload,
                    run.created_at,
                )
                with Session(repository.engine) as session:
                    locked_job = session.scalar(
                        select(ReplayJobRecord)
                        .where(ReplayJobRecord.job_id == job_id)
                        .with_for_update()
                    )
                    if locked_job.status == "COMPLETED":
                        return {
                            "job_id": job_id,
                            "status": "COMPLETED",
                            "result_digest": locked_job.result_digest,
                            "idempotent_replay": True,
                        }
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    locked_job.status = "COMPLETED"
                    locked_job.span_id = span_id
                    locked_job.trace_id = actual_trace_id
                    locked_job.completed_at = utcnow()
                    locked_job.updated_at = locked_job.completed_at
                    locked_job.duration_ms = elapsed_ms
                    locked_job.result_digest = result_digest
                    locked_job.result_payload = result_payload | {"object_path": branch_path}
                    locked_job.error = None
                    locked_job.signoz_trace_url = signoz_trace_url(actual_trace_id)
                    campaign = session.get(CampaignRecord, campaign_id)
                    counts = repository.refresh_counts(session, campaign)
                    repository.add_event(
                        session,
                        campaign_id,
                        "job.completed",
                        {
                            "job_id": job_id,
                            "replay_id": replay_id,
                            "trace_id": actual_trace_id,
                            "result_digest": result_digest,
                            "counts": counts.as_dict(),
                        },
                    )
                    session.commit()
            span.set_attribute("orbital.replay.result_digest", result_digest)
            span.set_attribute("orbital.replay.success", run.success)
            replay_duration.record(
                (time.perf_counter() - started) * 1000,
                {"orbital.campaign.id": campaign_id},
            )
            emit_event(
                "replay.job.completed",
                campaign_id=campaign_id,
                job_id=job_id,
                trace_id=actual_trace_id,
                result_digest=result_digest,
            )
            return {
                "job_id": job_id,
                "status": "COMPLETED",
                "result_digest": result_digest,
                "trace_id": actual_trace_id,
                "object_path": branch_path,
            }
    except (TimeoutError, IntegrityError) as exc:
        worker_retries.add(1)
        with traced(
            "replay.retry",
            {
                "orbital.campaign.id": campaign_id,
                "orbital.replay.job_id": job_id,
                "exception.type": type(exc).__name__,
                "orbital.signal.class": "campaign",
            },
        ):
            pass
        with Session(repository.engine) as session:
            job = session.get(ReplayJobRecord, job_id)
            if job and job.status != "COMPLETED":
                job.status = "QUEUED"
                job.retries += 1
                job.error = str(exc)
                job.updated_at = utcnow()
                repository.add_event(
                    session,
                    campaign_id,
                    "job.retry",
                    {
                        "job_id": job_id,
                        "retry": job.retries,
                        "reason": type(exc).__name__,
                    },
                )
                session.commit()
        try:
            raise self.retry(exc=exc, countdown=1)
        except MaxRetriesExceededError:
            with Session(repository.engine) as session:
                job = session.get(ReplayJobRecord, job_id)
                job.status = "FAILED"
                job.error = str(exc)
                job.updated_at = utcnow()
                session.commit()
            return {"job_id": job_id, "status": "FAILED", "error": str(exc)}
    except Exception as exc:
        postgres_failures.add(1, {"exception.type": type(exc).__name__})
        with traced(
            "replay.worker.failure",
            {
                "orbital.campaign.id": campaign_id,
                "orbital.replay.job_id": job_id,
                "exception.type": type(exc).__name__,
                "orbital.signal.class": "campaign",
            },
        ):
            pass
        emit_event(
            "replay.job.failure",
            campaign_id=campaign_id,
            job_id=job_id,
            error_type=type(exc).__name__,
        )
        raise
    finally:
        worker_active.add(-1)


@app.task(name="orbital.replay.complete_campaign")
def complete_campaign(results: list[dict[str, Any]], campaign_id: str) -> dict[str, Any]:
    with traced(
        "campaign.chord.complete",
        {
            "orbital.campaign.id": campaign_id,
            "orbital.chord.result_count": len(results),
            "orbital.signal.class": "campaign",
        },
    ):
        with Session(repository.engine) as session:
            campaign = session.scalar(
                select(CampaignRecord)
                .where(CampaignRecord.campaign_id == campaign_id)
                .with_for_update()
            )
            if not campaign:
                return {"campaign_id": campaign_id, "status": "MISSING"}
            counts = repository.refresh_counts(session, campaign)
            if campaign.status == "CANCELLED":
                target = "CANCELLED"
            elif campaign.status == "PAUSED":
                target = "PAUSED"
            elif counts.completed == counts.total and counts.total > 0:
                target = "COMPLETED"
            else:
                target = "PARTIAL"
            summary = {
                "counts": counts.as_dict(),
                "successful": sum(
                    bool((item or {}).get("status") == "COMPLETED") for item in results
                ),
                "chord_results": len(results),
            }
            campaign.result_summary = summary
            if target != campaign.status:
                repository.transition(
                    session,
                    campaign,
                    target,
                    "campaign.chord.completed",
                    summary,
                )
            else:
                repository.add_event(
                    session,
                    campaign_id,
                    "campaign.chord.completed",
                    {"status": target, **summary},
                )
            export = repository.campaign_payload(session, campaign)
            session.commit()
        export_digest = sha256_digest(export)
        export_path = versioned_path(
            "campaign-exports",
            campaign_id,
            export_digest,
            "campaign.json",
        )
        objects.put_json(export_path, "campaign_export", campaign_id, export)
        with Session(repository.engine) as session:
            campaign = session.get(CampaignRecord, campaign_id)
            campaign.result_summary = (campaign.result_summary or {}) | {
                "export_path": export_path,
                "export_digest": export_digest,
            }
            session.commit()
        return {
            "campaign_id": campaign_id,
            "status": target,
            "counts": counts.as_dict(),
            "export_path": export_path,
        }


@app.task(
    bind=True,
    name="orbital.range.execute_branch",
    max_retries=3,
    default_retry_delay=1,
    autoretry_for=(SQLAlchemyError, IntegrityError),
    retry_backoff=True,
    retry_jitter=False,
)
def execute_range_branch(self, branch_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    with Session(repository.engine) as session:
        branch = session.scalar(
            select(AdaptiveBranchRecord)
            .where(AdaptiveBranchRecord.branch_id == branch_id)
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
        parent_score: float | None = None
        if branch.parent_branch_id:
            parent = session.get(AdaptiveBranchRecord, branch.parent_branch_id)
            if not parent or parent.status != "COMPLETED":
                raise self.retry(
                    exc=RuntimeError("adaptive parent branch is not complete"),
                    countdown=1,
                )
            parent_score = float((parent.result_payload or {})["adaptive_score"])
        campaign = session.get(RangeCampaignRecord, branch.campaign_id)
        score_record = session.get(RangeScoreRecord, branch.seed_mutation_id)
        mutation_record = session.get(MutationRecord, branch.seed_mutation_id)
        if not campaign or not score_record or not mutation_record:
            return {"branch_id": branch_id, "status": "MISSING_INPUT"}
        branch.status = "RUNNING"
        branch.delivery_count += 1
        session.commit()
        trace_id = branch.trace_id
        campaign_id = branch.campaign_id
        proposal_payload = branch.proposal
        catalogue_digest = campaign.catalogue_digest
        seed_payload = mutation_record.payload

    context = _trace_context(trace_id, branch_id)
    with trace.get_tracer("orbital-replay-worker").start_as_current_span(
        "range.adaptive.execute",
        context=context,
        attributes={
            "orbital.range.campaign.id": campaign_id,
            "orbital.range.branch.id": branch_id,
            "orbital.range.generation": proposal_payload["generation"],
            "orbital.range.beam_index": proposal_payload["beam_index"],
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.signal.class": "campaign",
        },
    ) as span:
        actual_trace_id, _ = current_trace_ids()
        proposal = AdaptiveProposal.model_validate(proposal_payload)
        seed_score = score_mutation(
            ReplayMutation.model_validate(seed_payload), catalogue_digest
        )
        result_payload = evaluate_branch(seed_score, proposal, parent_score)
        result_payload |= {
            "branch_id": branch_id,
            "campaign_id": campaign_id,
            "trace_id": actual_trace_id,
        }
        result_digest = sha256_digest(result_payload)
        path = versioned_path(
            "adaptive-branches", branch_id, result_digest, "result.json"
        )
        storage_result = objects.put_json(
            path, "adaptive_branch", campaign_id, result_payload
        )
        with Session(repository.engine) as session:
            branch = session.get(AdaptiveBranchRecord, branch_id)
            if branch.status != "COMPLETED":
                branch.status = "COMPLETED"
                branch.result_payload = result_payload
                branch.result_digest = result_digest
                branch.object_path = path
                branch.checksum = storage_result["checksum"]
                branch.completed_at = utcnow()
                campaign = session.get(RangeCampaignRecord, campaign_id)
                campaign.status = "RUNNING"
                campaign.budget_used = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AdaptiveBranchRecord)
                        .where(
                            AdaptiveBranchRecord.campaign_id == campaign_id,
                            AdaptiveBranchRecord.status == "COMPLETED",
                        )
                    )
                    or 0
                )
                session.commit()
        range_branches.add(
            1,
            {
                "orbital.range.generation": proposal.generation,
                "orbital.range.proposal.source": proposal.source,
            },
        )
        range_duration.record((time.perf_counter() - started) * 1000)
        span.set_attribute("orbital.range.adaptive_score", result_payload["adaptive_score"])
        emit_event(
            "range.adaptive.branch.completed",
            campaign_id=campaign_id,
            branch_id=branch_id,
            trace_id=actual_trace_id,
            result_digest=result_digest,
        )
        return {
            "branch_id": branch_id,
            "status": "COMPLETED",
            "result_digest": result_digest,
            "trace_id": actual_trace_id,
            "object_path": path,
        }


@app.task(name="orbital.range.complete_campaign")
def complete_range_campaign(campaign_id: str) -> dict[str, Any]:
    with traced(
        "range.adaptive.chord.complete",
        {
            "orbital.range.campaign.id": campaign_id,
            "orbital.signal.class": "campaign",
        },
    ):
        with Session(repository.engine) as session:
            campaign = session.get(RangeCampaignRecord, campaign_id)
            if not campaign:
                return {"campaign_id": campaign_id, "status": "MISSING"}
            completed = int(
                session.scalar(
                    select(func.count())
                    .select_from(AdaptiveBranchRecord)
                    .where(
                        AdaptiveBranchRecord.campaign_id == campaign_id,
                        AdaptiveBranchRecord.status == "COMPLETED",
                    )
                )
                or 0
            )
            violations = int(
                sum(
                    bool((row.result_payload or {}).get("invariant_violation_observed"))
                    for row in session.scalars(
                        select(AdaptiveBranchRecord).where(
                            AdaptiveBranchRecord.campaign_id == campaign_id
                        )
                    ).all()
                )
            )
            campaign.budget_used = completed
            campaign.status = (
                "COMPLETED" if completed == campaign.search_budget else "PARTIAL"
            )
            campaign.completed_at = utcnow()
            summary = {
                "completed_branches": completed,
                "expected_branches": campaign.search_budget,
                "violations_observed": violations,
                "budget_exhausted": completed == campaign.search_budget,
                "stop_reason": (
                    "maximum_generations_reached"
                    if completed == campaign.search_budget
                    else "partial_execution"
                ),
            }
            campaign.result_summary = (campaign.result_summary or {}) | summary
            status = campaign.status
            session.commit()
        digest = sha256_digest(summary)
        path = versioned_path(
            "campaign-exports", campaign_id, digest, "range-campaign.json"
        )
        objects.put_json(path, "range_campaign_export", campaign_id, summary)
        return {
            "campaign_id": campaign_id,
            "status": status,
            **summary,
            "object_path": path,
        }


@app.task(
    bind=True,
    name="orbital.metamorphic.evaluate_case",
    max_retries=3,
    default_retry_delay=1,
    autoretry_for=(SQLAlchemyError, IntegrityError),
    retry_backoff=True,
    retry_jitter=False,
)
def execute_metamorphic_case(self, case_id: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        case = session.scalar(
            select(MetamorphicCaseRecord)
            .where(MetamorphicCaseRecord.case_id == case_id)
            .with_for_update()
        )
        if not case:
            return {"case_id": case_id, "status": "MISSING"}
        if case.status == "COMPLETED":
            case.delivery_count += 1
            session.commit()
            return {
                "case_id": case_id,
                "status": "COMPLETED",
                "result_digest": case.result_digest,
                "idempotent_replay": True,
            }
        case.status = "RUNNING"
        case.delivery_count += 1
        session.commit()
        trace_id = case.trace_id
        suite_id = case.suite_id
        invariant = case.invariant
        fixture = case.input_payload["fixture"]

    context = _trace_context(trace_id, case_id)
    with trace.get_tracer("orbital-replay-worker").start_as_current_span(
        "metamorphic.invariant.evaluate",
        context=context,
        attributes={
            "orbital.metamorphic.suite.id": suite_id,
            "orbital.metamorphic.case.id": case_id,
            "orbital.metamorphic.invariant": invariant,
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.signal.class": "campaign",
        },
    ):
        actual_trace_id, _ = current_trace_ids()
        result = evaluate_invariant(invariant, fixture)
        payload = result.model_dump(mode="json") | {
            "case_id": case_id,
            "suite_id": suite_id,
            "trace_id": actual_trace_id,
        }
        result_digest = sha256_digest(payload)
        path = versioned_path(
            "metamorphic-results", case_id, result_digest, "result.json"
        )
        storage_result = objects.put_json(
            path, "metamorphic_result", suite_id, payload
        )
        with Session(repository.engine) as session:
            case = session.get(MetamorphicCaseRecord, case_id)
            if case.status != "COMPLETED":
                case.status = "COMPLETED"
                case.result_payload = payload
                case.result_digest = result_digest
                case.object_path = path
                case.checksum = storage_result["checksum"]
                case.completed_at = utcnow()
                session.commit()
        metamorphic_evaluations.add(1, {"orbital.metamorphic.invariant": invariant})
        if not result.passed:
            metamorphic_failures.add(1, {"orbital.metamorphic.invariant": invariant})
        emit_event(
            "metamorphic.invariant.completed",
            suite_id=suite_id,
            case_id=case_id,
            invariant=invariant,
            passed=result.passed,
            trace_id=actual_trace_id,
        )
        return {
            "case_id": case_id,
            "status": "COMPLETED",
            "passed": result.passed,
            "result_digest": result_digest,
            "trace_id": actual_trace_id,
            "object_path": path,
        }


@app.task(name="orbital.metamorphic.complete_suite")
def complete_metamorphic_suite(
    results: list[dict[str, Any]], suite_id: str
) -> dict[str, Any]:
    passed = sum(bool(item.get("passed")) for item in results)
    payload = {
        "suite_id": suite_id,
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "complete": all(item.get("status") == "COMPLETED" for item in results),
    }
    current = repository.object_store.get(suite_id) or {}
    repository.object_store.put(
        suite_id, "metamorphic_suite", current | payload, utcnow()
    )
    emit_event("metamorphic.suite.completed", **payload)
    return payload
