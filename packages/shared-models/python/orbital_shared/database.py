from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# Stable, project-specific PostgreSQL advisory-lock key. Every API process starts
# concurrently during bootstrap, so schema creation must be serialized until
# Alembic becomes the sole migration owner.
_SCHEMA_LOCK_KEY = 0x4F52424954414C  # ASCII "ORBITAL"


class Base(DeclarativeBase):
    pass


class ObjectRecord(Base):
    __tablename__ = "orbital_objects"

    object_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CapabilityNonce(Base):
    __tablename__ = "capability_nonces"

    jti: Mapped[str] = mapped_column(String(128), primary_key=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    receipt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class RolloutState(Base):
    __tablename__ = "rollout_state"

    flag: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    percentage: Mapped[int] = mapped_column(Integer, default=0)
    certificate_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class CapsuleRecord(Base):
    __tablename__ = "mission_capsules"

    capsule_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_digest: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    template: Mapped[str] = mapped_column(String(128), index=True)
    variant: Mapped[int] = mapped_column(Integer)
    object_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(80))
    artifact_manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MutationRecord(Base):
    __tablename__ = "replay_mutations"
    __table_args__ = (
        UniqueConstraint(
            "source_capsule_id",
            "category",
            "operator",
            "seed",
            "sequence",
            name="uq_mutation_provenance",
        ),
    )

    mutation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_capsule_id: Mapped[str] = mapped_column(
        ForeignKey("mission_capsules.capsule_id", ondelete="CASCADE"), index=True
    )
    source_capsule_digest: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    operator: Mapped[str] = mapped_column(String(128), index=True)
    operator_version: Mapped[str] = mapped_column(String(32))
    seed: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    provenance_digest: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    mutation_digest: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    mutated_fixture_digest: Mapped[str] = mapped_column(String(80))
    object_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(80))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    reproducible: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RangeCampaignRecord(Base):
    __tablename__ = "range_campaigns"

    campaign_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_digest: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    catalogue_digest: Mapped[str] = mapped_column(String(80), index=True)
    selection_digest: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    beam_width: Mapped[int] = mapped_column(Integer)
    max_generations: Mapped[int] = mapped_column(Integer)
    search_budget: Mapped[int] = mapped_column(Integer)
    budget_used: Mapped[int] = mapped_column(Integer, default=0)
    selected_count: Mapped[int] = mapped_column(Integer)
    proposal_source: Mapped[str] = mapped_column(String(64))
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RangeScoreRecord(Base):
    __tablename__ = "range_mutation_scores"

    mutation_id: Mapped[str] = mapped_column(
        ForeignKey("replay_mutations.mutation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("range_campaigns.campaign_id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    total_score: Mapped[float] = mapped_column(Float)
    factors: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    score_digest: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdaptiveBranchRecord(Base):
    __tablename__ = "range_adaptive_branches"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "seed_mutation_id",
            "generation",
            "beam_index",
            name="uq_range_branch",
        ),
    )

    branch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("range_campaigns.campaign_id", ondelete="CASCADE"), index=True
    )
    seed_mutation_id: Mapped[str] = mapped_column(String(128), index=True)
    parent_branch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generation: Mapped[int] = mapped_column(Integer)
    beam_index: Mapped[int] = mapped_column(Integer)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    delivery_count: Mapped[int] = mapped_column(Integer, default=0)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSON)
    proposal_digest: Mapped[str] = mapped_column(String(80))
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    object_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MetamorphicCaseRecord(Base):
    __tablename__ = "metamorphic_cases"

    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    suite_id: Mapped[str] = mapped_column(String(128), index=True)
    invariant: Mapped[str] = mapped_column(String(128), index=True)
    capsule_id: Mapped[str] = mapped_column(String(128), index=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    delivery_count: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    object_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StorageObjectRecord(Base):
    __tablename__ = "storage_objects"

    object_path: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    minio_version_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampaignRecord(Base):
    __tablename__ = "campaigns"

    campaign_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_digest: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    candidate_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_digest: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_jobs: Mapped[int] = mapped_column(Integer)
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    retried_jobs: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    storage_status: Mapped[str] = mapped_column(String(32), default="AVAILABLE")
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReplayJobRecord(Base):
    __tablename__ = "replay_jobs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "capsule_id", "mutation_id", name="uq_replay_input"),
    )

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), index=True
    )
    mission_id: Mapped[str] = mapped_column(String(128), unique=True)
    replay_id: Mapped[str] = mapped_column(String(128), unique=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    candidate_id: Mapped[str] = mapped_column(String(128), index=True)
    capsule_id: Mapped[str] = mapped_column(String(128), index=True)
    mutation_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    delivery_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    signoz_trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampaignEventRecord(Base):
    __tablename__ = "campaign_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def engine_from_env():
    url = os.getenv("DATABASE_URL", "sqlite:///./orbital.db")
    return create_engine(url, pool_pre_ping=True)


class ObjectStore:
    def __init__(self) -> None:
        self.engine = engine_from_env()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
            Base.metadata.create_all(connection)

    def put(self, object_id: str, kind: str, payload: dict[str, Any], created_at: datetime) -> None:
        with Session(self.engine) as session:
            existing = session.get(ObjectRecord, object_id)
            if existing:
                existing.payload = payload
                existing.kind = kind
            else:
                session.add(
                    ObjectRecord(
                        object_id=object_id, kind=kind, payload=payload, created_at=created_at
                    )
                )
            session.commit()

    def get(self, object_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            record = session.get(ObjectRecord, object_id)
            return record.payload if record else None

    def list(self, kind: str, limit: int = 1000) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ObjectRecord)
                .where(ObjectRecord.kind == kind)
                .order_by(ObjectRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [row.payload for row in rows]

    def count(self, kind: str) -> int:
        with Session(self.engine) as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(ObjectRecord).where(ObjectRecord.kind == kind)
                )
                or 0
            )
