from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbital_shared.database import (
    CampaignEventRecord,
    CampaignRecord,
    CapsuleRecord,
    ObjectStore,
    ReplayJobRecord,
    StorageObjectRecord,
)
from orbital_shared.models import sha256_digest, utcnow

CAMPAIGN_STATES = {
    "CREATED",
    "QUEUED",
    "RUNNING",
    "PAUSED",
    "PARTIAL",
    "FAILED",
    "COMPLETED",
    "CANCELLED",
}
TERMINAL_STATES = {"FAILED", "COMPLETED", "CANCELLED"}
TRANSITIONS = {
    "CREATED": {"QUEUED", "PAUSED", "CANCELLED", "FAILED"},
    "QUEUED": {"RUNNING", "PAUSED", "PARTIAL", "CANCELLED", "FAILED"},
    "RUNNING": {"QUEUED", "PAUSED", "PARTIAL", "COMPLETED", "CANCELLED", "FAILED"},
    "PAUSED": {"QUEUED", "RUNNING", "CANCELLED", "FAILED"},
    "PARTIAL": {"QUEUED", "RUNNING", "COMPLETED", "CANCELLED", "FAILED"},
    "FAILED": {"QUEUED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def content_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()


def checksum_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class IntegrityError(RuntimeError):
    pass


def decode_verified_json(payload: bytes, expected_checksum: str | None = None) -> Any:
    actual = checksum_bytes(payload)
    if expected_checksum and actual != expected_checksum:
        raise IntegrityError(
            f"checksum mismatch: expected {expected_checksum}, got {actual}"
        )
    return json.loads(payload)


def digest_suffix(digest: str) -> str:
    return digest.removeprefix("sha256:")


def versioned_path(kind: str, owner_id: str, digest: str, filename: str) -> str:
    return f"{kind}/v1/{owner_id}/{digest_suffix(digest)}/{filename}"


def stable_identifier(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}_{digest_suffix(sha256_digest(value))[:length]}"


def deterministic_trace_id(value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:32]
    return digest if int(digest, 16) else ("1" + digest[1:])


def validate_transition(current: str, target: str) -> None:
    if target == current:
        return
    if current not in TRANSITIONS or target not in TRANSITIONS[current]:
        raise ValueError(f"invalid campaign transition {current} -> {target}")


@dataclass(frozen=True)
class CampaignCounts:
    total: int
    completed: int
    running: int
    queued: int
    failed: int
    retried: int
    cancelled: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "completed": self.completed,
            "running": self.running,
            "queued": self.queued,
            "failed": self.failed,
            "retried": self.retried,
            "cancelled": self.cancelled,
        }


class CampaignRepository:
    def __init__(self) -> None:
        self.object_store = ObjectStore()
        self.engine = self.object_store.engine

    def add_event(
        self, session: Session, campaign_id: str, event_type: str, payload: dict[str, Any]
    ) -> CampaignEventRecord:
        now = utcnow()
        event = CampaignEventRecord(
            event_id=stable_identifier(
                "evt", [campaign_id, event_type, payload, now.isoformat()], length=32
            ),
            campaign_id=campaign_id,
            event_type=event_type,
            payload=payload,
            created_at=now,
        )
        session.add(event)
        session.flush()
        return event

    def counts(self, session: Session, campaign_id: str) -> CampaignCounts:
        rows = session.execute(
            select(ReplayJobRecord.status, func.count(), func.sum(ReplayJobRecord.retries))
            .where(ReplayJobRecord.campaign_id == campaign_id)
            .group_by(ReplayJobRecord.status)
        ).all()
        by_status = {status: int(count) for status, count, _ in rows}
        retries = sum(int(retry_count or 0) for _, _, retry_count in rows)
        total = sum(by_status.values())
        return CampaignCounts(
            total=total,
            completed=by_status.get("COMPLETED", 0),
            running=by_status.get("RUNNING", 0),
            queued=by_status.get("QUEUED", 0) + by_status.get("CREATED", 0),
            failed=by_status.get("FAILED", 0) + by_status.get("TIMED_OUT", 0),
            retried=retries,
            cancelled=by_status.get("CANCELLED", 0),
        )

    def refresh_counts(self, session: Session, campaign: CampaignRecord) -> CampaignCounts:
        counts = self.counts(session, campaign.campaign_id)
        campaign.completed_jobs = counts.completed
        campaign.failed_jobs = counts.failed
        campaign.retried_jobs = counts.retried
        campaign.updated_at = utcnow()
        return counts

    def campaign_payload(
        self, session: Session, campaign: CampaignRecord, storage_status: str | None = None
    ) -> dict[str, Any]:
        counts = self.refresh_counts(session, campaign)
        jobs = session.scalars(
            select(ReplayJobRecord)
            .where(ReplayJobRecord.campaign_id == campaign.campaign_id)
            .order_by(ReplayJobRecord.created_at)
        ).all()
        return {
            "campaign_id": campaign.campaign_id,
            "candidate_id": campaign.candidate_id,
            "artifact_digest": campaign.artifact_digest,
            "status": campaign.status,
            "counts": counts.as_dict(),
            "storage_status": storage_status or campaign.storage_status,
            "availability_state": (
                "READY"
                if (storage_status or campaign.storage_status) == "AVAILABLE"
                else "UNKNOWN"
            ),
            "state_version": campaign.state_version,
            "created_at": campaign.created_at.isoformat(),
            "updated_at": campaign.updated_at.isoformat(),
            "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
            "result_summary": campaign.result_summary or {},
            "jobs": [
                {
                    "job_id": job.job_id,
                    "mission_id": job.mission_id,
                    "replay_id": job.replay_id,
                    "trace_id": job.trace_id,
                    "span_id": job.span_id,
                    "candidate_id": job.candidate_id,
                    "capsule_id": job.capsule_id,
                    "mutation_id": job.mutation_id or None,
                    "status": job.status,
                    "retries": job.retries,
                    "delivery_count": job.delivery_count,
                    "duration_ms": job.duration_ms,
                    "result_digest": job.result_digest,
                    "signoz_trace_url": job.signoz_trace_url,
                    "error": job.error,
                }
                for job in jobs
            ],
        }

    def transition(
        self,
        session: Session,
        campaign: CampaignRecord,
        target: str,
        event_type: str,
        detail: dict[str, Any] | None = None,
    ) -> CampaignCounts:
        validate_transition(campaign.status, target)
        campaign.status = target
        campaign.state_version += 1
        campaign.updated_at = utcnow()
        if target == "QUEUED" and campaign.queued_at is None:
            campaign.queued_at = campaign.updated_at
        if target == "RUNNING" and campaign.started_at is None:
            campaign.started_at = campaign.updated_at
        if target in TERMINAL_STATES:
            campaign.completed_at = campaign.updated_at
        counts = self.refresh_counts(session, campaign)
        self.add_event(
            session,
            campaign.campaign_id,
            event_type,
            {
                "status": target,
                "counts": counts.as_dict(),
                "state_version": campaign.state_version,
                **(detail or {}),
            },
        )
        return counts

    def events(self, campaign_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(CampaignEventRecord)
                .where(
                    CampaignEventRecord.campaign_id == campaign_id,
                    CampaignEventRecord.sequence > after,
                )
                .order_by(CampaignEventRecord.sequence)
                .limit(limit)
            ).all()
            return [
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "event_type": row.event_type,
                    "created_at": row.created_at.isoformat(),
                    **row.payload,
                }
                for row in rows
            ]

    def object_counts(self) -> dict[str, int]:
        with Session(self.engine) as session:
            return {
                "capsules": int(
                    session.scalar(select(func.count()).select_from(CapsuleRecord)) or 0
                ),
                "storage_objects": int(
                    session.scalar(select(func.count()).select_from(StorageObjectRecord)) or 0
                ),
                "campaigns": int(
                    session.scalar(select(func.count()).select_from(CampaignRecord)) or 0
                ),
                "replay_jobs": int(
                    session.scalar(select(func.count()).select_from(ReplayJobRecord)) or 0
                ),
            }


def signoz_trace_url(trace_id: str) -> str:
    base = os.getenv("SIGNOZ_PUBLIC_URL", "http://localhost:8080").rstrip("/")
    return f"{base}/trace/{trace_id}"
