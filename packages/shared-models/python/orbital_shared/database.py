from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


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


def engine_from_env():
    url = os.getenv("DATABASE_URL", "sqlite:///./orbital.db")
    return create_engine(url, pool_pre_ping=True)


class ObjectStore:
    def __init__(self) -> None:
        self.engine = engine_from_env()
        Base.metadata.create_all(self.engine)

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
