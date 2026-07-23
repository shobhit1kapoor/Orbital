from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime
from typing import Any

from campaign_runtime import replay_outcome
from fastapi import Header, HTTPException, Query, Request
from opentelemetry import metrics
from orbital_semconv import current_trace_ids, emit_event, traced
from orbital_shared.api import create_service
from orbital_shared.campaigns import (
    TERMINAL_STATES,
    CampaignRepository,
    deterministic_trace_id,
    stable_identifier,
    versioned_path,
)
from orbital_shared.database import (
    CampaignRecord,
    CapsuleRecord,
    MetamorphicCaseRecord,
    ReplayJobRecord,
)
from orbital_shared.metamorphic import INVARIANTS, default_fixture
from orbital_shared.models import (
    AuthorityLevel,
    ReplayRun,
    sha256_digest,
    utcnow,
)
from orbital_shared.object_storage import VersionedObjectStorage
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from worker import (
    dispatch_campaign,
    dispatch_metamorphic_suite,
    execute_metamorphic_case,
    execute_replay_job,
)

app = create_service("ORBITAL Σ Replay Orchestrator", "orbital-replay-orchestrator")
repository = CampaignRepository()
store = repository.object_store
objects = VersionedObjectStorage()
meter = metrics.get_meter("orbital-replay-orchestrator")
campaign_created = meter.create_counter("orbital.campaign.created")
campaign_recovered = meter.create_counter("orbital.campaign.recovered")
campaign_controls = meter.create_counter("orbital.campaign.lifecycle.operations")
watchdog_task: asyncio.Task[None] | None = None


class ReplayRequest(BaseModel):
    candidate_id: str
    artifact_digest: str
    capsule_ids: list[str]
    mutation_ids: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = AuthorityLevel.LOW_VALUE_ACTION
    mode: str = "deterministic_simulation"
    seed: int = 20260722


class CampaignRequest(ReplayRequest):
    submission_key: str = "phase3-default"
    job_delay_ms: int = Field(default=0, ge=0, le=5000)
    fail_once_indices: list[int] = Field(default_factory=list)
    start_paused: bool = False


class MetamorphicRequest(BaseModel):
    source_run_id: str
    transformations: list[str]


class MetamorphicSuiteRequest(BaseModel):
    capsule_ids: list[str] = Field(default_factory=list)
    submission_key: str = "phase4b-metamorphic-v1"


def _job_pairs(request: CampaignRequest) -> list[tuple[str, str]]:
    if not request.capsule_ids:
        raise HTTPException(422, "at least one capsule is required")
    if not request.mutation_ids:
        return [(capsule_id, "") for capsule_id in request.capsule_ids]
    size = max(len(request.capsule_ids), len(request.mutation_ids))
    return [
        (
            request.capsule_ids[index % len(request.capsule_ids)],
            request.mutation_ids[index % len(request.mutation_ids)],
        )
        for index in range(size)
    ]


def _sync_run_one(
    request: ReplayRequest,
    capsule_id: str,
    mutation_id: str,
    index: int,
) -> ReplayRun:
    replay_id = stable_identifier(
        "run",
        [
            request.candidate_id,
            request.artifact_digest,
            capsule_id,
            mutation_id,
            request.seed,
            index,
        ],
    )
    mission_id = stable_identifier("mis", replay_id)
    trace_id = deterministic_trace_id(replay_id)
    mutation = store.get(mutation_id) if mutation_id else None
    return replay_outcome(
        candidate_id=request.candidate_id,
        artifact_digest=request.artifact_digest,
        capsule_id=capsule_id,
        mutation_id=mutation_id,
        mutation=mutation,
        mode=request.mode,
        seed=request.seed,
        mission_id=mission_id,
        trace_id=trace_id,
        span_id="",
        replay_id=replay_id,
        authority_level=request.authority_level,
    )


@app.post("/v1/replays")
def run_replays(request: ReplayRequest) -> dict[str, Any]:
    pairs = _job_pairs(CampaignRequest(**request.model_dump())) if request.capsule_ids else []
    runs = [
        _sync_run_one(request, capsule_id, mutation_id, index)
        for index, (capsule_id, mutation_id) in enumerate(pairs)
    ]
    for run in runs:
        store.put(run.run_id, "replay_run", run.model_dump(mode="json"), run.created_at)
    successful = sum(run.success for run in runs)
    escaped = sum(run.unsafe_escaped for run in runs)
    return {
        "count": len(runs),
        "successful": successful,
        "unsafe_escaped": escaped,
        "success_rate": successful / len(runs) if runs else 0,
        "mean_replay_fidelity": (
            sum(run.replay_fidelity for run in runs) / len(runs) if runs else 0
        ),
        "run_ids": [run.run_id for run in runs],
    }


@app.get("/v1/replays/{run_id}")
def replay(run_id: str) -> dict[str, Any] | None:
    return store.get(run_id)


@app.post("/v1/campaigns", status_code=202)
def create_campaign(request: CampaignRequest) -> dict[str, Any]:
    pairs = _job_pairs(request)
    request_payload = request.model_dump(mode="json")
    submission_digest = sha256_digest(request_payload)
    campaign_id = stable_identifier("campaign", submission_digest)
    now = utcnow()
    with traced(
        "campaign.create",
        {
            "orbital.campaign.id": campaign_id,
            "orbital.candidate.id": request.candidate_id,
            "orbital.campaign.job_count": len(pairs),
            "orbital.signal.class": "campaign",
        },
    ):
        with Session(repository.engine) as session:
            existing = session.scalar(
                select(CampaignRecord).where(CampaignRecord.submission_digest == submission_digest)
            )
            if existing:
                payload = repository.campaign_payload(
                    session,
                    existing,
                    objects.health(),
                )
                session.commit()
                return payload | {"duplicate_submission": True}
            capsule_ids = set(request.capsule_ids)
            known_capsules = set(
                session.scalars(
                    select(CapsuleRecord.capsule_id).where(
                        CapsuleRecord.capsule_id.in_(capsule_ids)
                    )
                ).all()
            )
            missing = sorted(capsule_ids - known_capsules)
            if missing:
                raise HTTPException(422, f"capsules are not persisted: {missing[:5]}")
            campaign = CampaignRecord(
                campaign_id=campaign_id,
                submission_digest=submission_digest,
                candidate_id=request.candidate_id,
                artifact_digest=request.artifact_digest,
                status="CREATED",
                requested_jobs=len(pairs),
                completed_jobs=0,
                failed_jobs=0,
                retried_jobs=0,
                request_payload=request_payload,
                result_summary={},
                storage_status=objects.health(),
                state_version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(campaign)
            session.flush()
            job_ids: list[str] = []
            for index, (capsule_id, mutation_id) in enumerate(pairs):
                job_id = stable_identifier(
                    "job",
                    [campaign_id, capsule_id, mutation_id, index],
                )
                replay_id = stable_identifier("replay", job_id)
                job_ids.append(job_id)
                session.add(
                    ReplayJobRecord(
                        job_id=job_id,
                        campaign_id=campaign_id,
                        mission_id=stable_identifier("mis", job_id),
                        replay_id=replay_id,
                        trace_id=deterministic_trace_id(job_id),
                        span_id=None,
                        candidate_id=request.candidate_id,
                        capsule_id=capsule_id,
                        mutation_id=mutation_id,
                        status="QUEUED",
                        retries=0,
                        delivery_count=0,
                        queued_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                if mutation_id:
                    mutation = store.get(mutation_id) or {
                        "mutation_id": mutation_id,
                        "status": "UNKNOWN",
                    }
                    mutation_digest = sha256_digest(mutation)
                    mutation_path = versioned_path(
                        "mutation-artifacts",
                        mutation_id,
                        mutation_digest,
                        "mutation.json",
                    )
                    objects.put_json(
                        mutation_path,
                        "mutation_artifact",
                        campaign_id,
                        mutation,
                    )
            fail_once_job_ids = [
                job_ids[index] for index in request.fail_once_indices if 0 <= index < len(job_ids)
            ]
            campaign.request_payload = request_payload | {"fail_once_job_ids": fail_once_job_ids}
            repository.transition(
                session,
                campaign,
                "PAUSED" if request.start_paused else "QUEUED",
                "campaign.created",
                {"job_ids": job_ids},
            )
            session.commit()
        for job_id in job_ids:
            with traced(
                "campaign.job.queued",
                {
                    "orbital.campaign.id": campaign_id,
                    "orbital.replay.job_id": job_id,
                    "orbital.signal.class": "campaign",
                },
            ):
                pass
        chord_id = None
        if not request.start_paused:
            chord_id = dispatch_campaign(campaign_id, job_ids)
        with Session(repository.engine) as session:
            campaign = session.get(CampaignRecord, campaign_id)
            campaign.result_summary = {"chord_id": chord_id}
            payload = repository.campaign_payload(session, campaign, objects.health())
            session.commit()
        campaign_created.add(1)
        emit_event(
            "campaign.created",
            campaign_id=campaign_id,
            jobs=len(job_ids),
            chord_id=chord_id,
        )
        return payload | {"duplicate_submission": False}


def _campaign(campaign_id: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        campaign = session.get(CampaignRecord, campaign_id)
        if not campaign:
            raise HTTPException(404, "campaign not found")
        storage_status = objects.health()
        if storage_status != "AVAILABLE":
            with traced(
                "campaign.storage.unavailable",
                {
                    "orbital.campaign.id": campaign_id,
                    "orbital.storage.status": storage_status,
                    "orbital.signal.class": "campaign",
                },
            ):
                pass
        payload = repository.campaign_payload(session, campaign, storage_status)
        session.commit()
        return payload


@app.get("/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    return _campaign(campaign_id)


def _dispatch_pending(campaign_id: str) -> tuple[list[str], str | None]:
    with Session(repository.engine) as session:
        jobs = session.scalars(
            select(ReplayJobRecord).where(
                ReplayJobRecord.campaign_id == campaign_id,
                ReplayJobRecord.status.in_(["CREATED", "QUEUED", "FAILED", "TIMED_OUT", "RUNNING"]),
            )
        ).all()
        now = utcnow()
        for job in jobs:
            job.status = "QUEUED"
            job.queued_at = now
            job.updated_at = now
        job_ids = [job.job_id for job in jobs]
        session.commit()
    return job_ids, dispatch_campaign(campaign_id, job_ids) if job_ids else None


async def _recovery_watchdog() -> None:
    while True:
        await asyncio.sleep(10)
        with Session(repository.engine) as session:
            rows = session.execute(
                select(
                    CampaignRecord.campaign_id,
                    func.max(ReplayJobRecord.updated_at),
                )
                .join(
                    ReplayJobRecord,
                    ReplayJobRecord.campaign_id == CampaignRecord.campaign_id,
                )
                .where(CampaignRecord.status.in_(["QUEUED", "RUNNING", "PARTIAL"]))
                .group_by(CampaignRecord.campaign_id)
            ).all()
        for campaign_id, last_job_update in rows:
            snapshot = _campaign(campaign_id)
            if (
                snapshot["counts"]["queued"] <= 0
                and snapshot["counts"]["running"] <= 0
            ):
                continue
            if last_job_update:
                age = datetime.now(UTC) - last_job_update
                if age.total_seconds() < 8:
                    continue
            with Session(repository.engine) as session:
                repository.add_event(
                    session,
                    campaign_id,
                    "campaign.recovery.watchdog",
                    {
                        "status": snapshot["status"],
                        "counts": snapshot["counts"],
                    },
                )
                session.commit()
            with traced(
                "campaign.recover",
                {
                    "orbital.campaign.id": campaign_id,
                    "orbital.signal.class": "campaign",
                    "orbital.recovery.mode": "watchdog",
                },
            ):
                _dispatch_pending(campaign_id)


@app.on_event("startup")
async def start_recovery_watchdog() -> None:
    global watchdog_task
    watchdog_task = asyncio.create_task(_recovery_watchdog())


@app.on_event("shutdown")
async def stop_recovery_watchdog() -> None:
    if watchdog_task:
        watchdog_task.cancel()


@app.post("/v1/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str) -> dict[str, Any]:
    with traced(
        "campaign.pause",
        {
            "orbital.campaign.id": campaign_id,
            "orbital.signal.class": "campaign",
        },
    ):
        with Session(repository.engine) as session:
            campaign = session.get(CampaignRecord, campaign_id)
            if not campaign:
                raise HTTPException(404, "campaign not found")
            if campaign.status in TERMINAL_STATES:
                raise HTTPException(409, f"cannot pause {campaign.status} campaign")
            if campaign.status != "PAUSED":
                repository.transition(session, campaign, "PAUSED", "campaign.paused")
            session.commit()
    campaign_controls.add(1, {"operation": "pause"})
    return _campaign(campaign_id)


@app.post("/v1/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str) -> dict[str, Any]:
    with traced(
        "campaign.resume",
        {
            "orbital.campaign.id": campaign_id,
            "orbital.signal.class": "campaign",
        },
    ):
        with Session(repository.engine) as session:
            campaign = session.get(CampaignRecord, campaign_id)
            if not campaign:
                raise HTTPException(404, "campaign not found")
            if campaign.status not in {"PAUSED", "PARTIAL", "FAILED"}:
                raise HTTPException(409, f"cannot resume {campaign.status} campaign")
            repository.transition(session, campaign, "QUEUED", "campaign.resumed")
            session.commit()
        job_ids, chord_id = _dispatch_pending(campaign_id)
    campaign_controls.add(1, {"operation": "resume"})
    return _campaign(campaign_id) | {"dispatched_jobs": len(job_ids), "chord_id": chord_id}


@app.post("/v1/campaigns/{campaign_id}/retry")
def retry_campaign(campaign_id: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        campaign = session.get(CampaignRecord, campaign_id)
        if not campaign:
            raise HTTPException(404, "campaign not found")
        jobs = session.scalars(
            select(ReplayJobRecord).where(
                ReplayJobRecord.campaign_id == campaign_id,
                ReplayJobRecord.status.in_(["FAILED", "TIMED_OUT"]),
            )
        ).all()
        if not jobs:
            return _campaign(campaign_id) | {"dispatched_jobs": 0}
        if campaign.status != "QUEUED":
            repository.transition(session, campaign, "QUEUED", "campaign.retry")
        session.commit()
    job_ids, chord_id = _dispatch_pending(campaign_id)
    campaign_controls.add(1, {"operation": "retry"})
    return _campaign(campaign_id) | {"dispatched_jobs": len(job_ids), "chord_id": chord_id}


@app.post("/v1/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        campaign = session.get(CampaignRecord, campaign_id)
        if not campaign:
            raise HTTPException(404, "campaign not found")
        if campaign.status not in TERMINAL_STATES:
            repository.transition(session, campaign, "CANCELLED", "campaign.cancelled")
        session.query(ReplayJobRecord).filter(
            ReplayJobRecord.campaign_id == campaign_id,
            ReplayJobRecord.status != "COMPLETED",
        ).update({"status": "CANCELLED", "updated_at": utcnow()})
        session.commit()
    campaign_controls.add(1, {"operation": "cancel"})
    return _campaign(campaign_id)


@app.post("/v1/campaigns/{campaign_id}/recover")
def recover_campaign(campaign_id: str) -> dict[str, Any]:
    with traced(
        "campaign.recover",
        {
            "orbital.campaign.id": campaign_id,
            "orbital.signal.class": "campaign",
        },
    ):
        with Session(repository.engine) as session:
            campaign = session.get(CampaignRecord, campaign_id)
            if not campaign:
                raise HTTPException(404, "campaign not found")
            if campaign.status == "COMPLETED":
                return _campaign(campaign_id) | {"recovered_jobs": 0}
            if campaign.status == "CANCELLED":
                raise HTTPException(409, "cancelled campaign cannot be recovered")
            if campaign.status != "QUEUED":
                repository.transition(session, campaign, "QUEUED", "campaign.recovered")
            session.commit()
        job_ids, chord_id = _dispatch_pending(campaign_id)
    campaign_recovered.add(1)
    return _campaign(campaign_id) | {
        "recovered_jobs": len(job_ids),
        "chord_id": chord_id,
    }


@app.post("/v1/campaigns/recover")
def recover_all_campaigns() -> dict[str, Any]:
    with Session(repository.engine) as session:
        ids = session.scalars(
            select(CampaignRecord.campaign_id).where(
                CampaignRecord.status.in_(["QUEUED", "RUNNING", "PARTIAL", "FAILED"])
            )
        ).all()
    results = [recover_campaign(campaign_id) for campaign_id in ids]
    return {"campaigns": len(results), "recovered_jobs": sum(r["recovered_jobs"] for r in results)}


@app.post("/v1/jobs/{job_id}/redeliver")
def redeliver_job(job_id: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        job = session.get(ReplayJobRecord, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        expected_digest = job.result_digest
        campaign_id = job.campaign_id
    result = execute_replay_job.apply_async(args=[job_id]).get(timeout=30)
    with Session(repository.engine) as session:
        job = session.get(ReplayJobRecord, job_id)
        return {
            "campaign_id": campaign_id,
            "job_id": job_id,
            "result": result,
            "expected_digest": expected_digest,
            "actual_digest": job.result_digest,
            "idempotent": expected_digest == job.result_digest,
            "delivery_count": job.delivery_count,
        }


@app.get("/v1/campaigns/{campaign_id}/events")
async def stream_campaign(
    request: Request,
    campaign_id: str,
    after: int = Query(default=0, ge=0),
    once: bool = False,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    _campaign(campaign_id)
    cursor = int(last_event_id or after)

    async def events():
        nonlocal cursor
        while True:
            rows = repository.events(campaign_id, cursor)
            for event in rows:
                cursor = event["sequence"]
                yield {
                    "id": str(cursor),
                    "event": event["event_type"],
                    "data": json.dumps(event),
                }
            snapshot = _campaign(campaign_id)
            if once:
                if not rows:
                    yield {
                        "id": str(cursor),
                        "event": "campaign.snapshot",
                        "data": json.dumps(snapshot),
                    }
                break
            if snapshot["status"] in TERMINAL_STATES and not rows:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(events(), ping=5)


@app.get("/v1/campaigns/stats")
def campaign_stats() -> dict[str, Any]:
    return repository.object_counts() | {"storage_status": objects.health()}


@app.post("/v1/metamorphic/suites", status_code=202)
def create_metamorphic_suite(request: MetamorphicSuiteRequest) -> dict[str, Any]:
    with Session(repository.engine) as session:
        if request.capsule_ids:
            capsule_ids = list(dict.fromkeys(request.capsule_ids))
            known = set(
                session.scalars(
                    select(CapsuleRecord.capsule_id).where(
                        CapsuleRecord.capsule_id.in_(capsule_ids)
                    )
                ).all()
            )
            missing = sorted(set(capsule_ids) - known)
            if missing:
                raise HTTPException(422, f"capsules are not persisted: {missing[:5]}")
        else:
            capsule_ids = list(
                session.scalars(
                    select(CapsuleRecord.capsule_id)
                    .order_by(CapsuleRecord.capsule_id)
                    .limit(len(INVARIANTS))
                ).all()
            )
    if not capsule_ids:
        raise HTTPException(409, "the Phase 4A capsule corpus is unavailable")
    suite_identity = {
        "submission_key": request.submission_key,
        "capsule_ids": capsule_ids,
        "invariants": list(INVARIANTS),
        "version": "phase4b.metamorphic.v1",
    }
    suite_id = stable_identifier("metasuite", suite_identity)
    existing = store.get(suite_id)
    if existing:
        return existing | {"duplicate_submission": True}

    now = utcnow()
    case_ids: list[str] = []
    with traced(
        "metamorphic.suite.create",
        {
            "orbital.metamorphic.suite.id": suite_id,
            "orbital.metamorphic.case_count": len(INVARIANTS),
            "orbital.signal.class": "campaign",
            "orbital.execution.mode": "deterministic_simulation",
        },
    ):
        trace_id, _ = current_trace_ids()
        with Session(repository.engine) as session:
            for index, invariant in enumerate(INVARIANTS):
                capsule_id = capsule_ids[index % len(capsule_ids)]
                case_id = stable_identifier(
                    "metacase", [suite_id, invariant, capsule_id]
                )
                case_ids.append(case_id)
                if not session.get(MetamorphicCaseRecord, case_id):
                    session.add(
                        MetamorphicCaseRecord(
                            case_id=case_id,
                            suite_id=suite_id,
                            invariant=invariant,
                            capsule_id=capsule_id,
                            trace_id=deterministic_trace_id(case_id),
                            status="QUEUED",
                            delivery_count=0,
                            retries=0,
                            input_payload={
                                "fixture": default_fixture(capsule_id),
                                "execution_mode": "deterministic_simulation",
                            },
                            created_at=now,
                        )
                    )
            session.commit()
        payload = {
            "suite_id": suite_id,
            "status": "QUEUED",
            "case_count": len(case_ids),
            "case_ids": case_ids,
            "invariants": list(INVARIANTS),
            "trace_id": trace_id,
            "execution_mode": "deterministic_simulation",
            "duplicate_submission": False,
        }
        store.put(suite_id, "metamorphic_suite", payload, now)
        chord_id = dispatch_metamorphic_suite(suite_id, case_ids)
        response = payload | {"chord_id": chord_id}
        emit_event("metamorphic.suite.created", **response)
        return response


@app.get("/v1/metamorphic/suites/{suite_id}")
def metamorphic_suite(suite_id: str) -> dict[str, Any]:
    summary = store.get(suite_id)
    with Session(repository.engine) as session:
        cases = list(
            session.scalars(
                select(MetamorphicCaseRecord)
                .where(MetamorphicCaseRecord.suite_id == suite_id)
                .order_by(MetamorphicCaseRecord.invariant)
            ).all()
        )
    if not cases and not summary:
        raise HTTPException(404, "metamorphic suite not found")
    completed = sum(item.status == "COMPLETED" for item in cases)
    passed = sum(bool((item.result_payload or {}).get("passed")) for item in cases)
    status = (
        "COMPLETED"
        if completed == len(cases) and cases
        else "RUNNING"
        if completed
        else "QUEUED"
    )
    return {
        **(summary or {}),
        "suite_id": suite_id,
        "status": status,
        "case_count": len(cases),
        "completed": completed,
        "passed": passed,
        "failed": completed - passed,
        "cases": [
            {
                "case_id": item.case_id,
                "invariant": item.invariant,
                "status": item.status,
                "passed": (item.result_payload or {}).get("passed"),
                "result_digest": item.result_digest,
                "object_path": item.object_path,
                "checksum": item.checksum,
                "trace_id": (item.result_payload or {}).get("trace_id", item.trace_id),
                "delivery_count": item.delivery_count,
                "retries": item.retries,
            }
            for item in cases
        ],
    }


@app.post("/v1/metamorphic/cases/{case_id}/redeliver", status_code=202)
def redeliver_metamorphic_case(case_id: str) -> dict[str, Any]:
    with Session(repository.engine) as session:
        case = session.get(MetamorphicCaseRecord, case_id)
        if not case:
            raise HTTPException(404, "metamorphic case not found")
        original_digest = case.result_digest
    task = execute_metamorphic_case.delay(case_id)
    return {
        "case_id": case_id,
        "task_id": str(task.id),
        "original_result_digest": original_digest,
        "expected_idempotent": original_digest is not None,
    }


@app.post("/v1/metamorphic/evaluate")
def metamorphic(request: MetamorphicRequest) -> dict[str, Any]:
    source = store.get(request.source_run_id)
    if not source:
        return {"passed": False, "reason": "source_run_not_found"}
    outcomes = []
    for transformation in request.transformations:
        expands_authority = transformation in {
            "irrelevant_text_expands_refund",
            "writing_style_changes_authorization",
            "split_denied_action",
            "cross_tenant_memory",
        } and source.get("unsafe_escaped", False)
        outcomes.append(
            {
                "transformation": transformation,
                "passed": not expands_authority,
                "before_authority": source["authority_level"],
                "after_authority": source["authority_level"],
            }
        )
    return {"passed": all(item["passed"] for item in outcomes), "outcomes": outcomes}


@app.get("/v1/replay-fidelity")
def fidelity() -> dict[str, float]:
    runs = store.list("replay_run", 5000)
    value = sum(run["replay_fidelity"] for run in runs) / len(runs) if runs else math.nan
    return {"replay_fidelity": value, "sample_size": len(runs)}
