from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import HTTPException
from opentelemetry import metrics
from orbital_semconv import current_trace_ids, emit_event, traced
from orbital_shared.api import create_service
from orbital_shared.campaigns import versioned_path
from orbital_shared.corpus import (
    CORPUS_VERSION,
    TEMPLATES,
    build_capsule,
    corpus_digest,
)
from orbital_shared.database import CapsuleRecord, ObjectStore
from orbital_shared.models import MissionCapsule, sha256_digest
from orbital_shared.object_storage import IntegrityError, VersionedObjectStorage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

app = create_service("ORBITAL Σ CAPSULE Builder", "orbital-capsule-builder")
store = ObjectStore()
objects = VersionedObjectStorage()
meter = metrics.get_meter("orbital-capsule-builder")
persistence_latency = meter.create_histogram(
    "orbital.minio.persistence.latency",
    unit="ms",
    description="MinIO object write latency",
)
capsules_created = meter.create_counter("orbital.capsule.created")
capsule_duplicates = meter.create_counter("orbital.capsule.duplicate")
corpus_generation_latency = meter.create_histogram(
    "orbital.capsule.corpus.generation.duration",
    unit="ms",
    description="Deterministic capsule corpus generation duration",
)


class BuildRequest(BaseModel):
    count_per_template: int = 10
    persist_files: bool = True


def persist_capsule(
    capsule: MissionCapsule, persist_file: bool, output_dir: Path
) -> tuple[bool, list[str]]:
    payload = capsule.model_dump(mode="json")
    artifact_values = {
        "user-request.json": payload["user_request"],
        "agent-artifacts.json": payload["agent_artifacts"],
        "prompt-snapshot.json": payload["prompt_snapshot"],
        "retrieval-fixtures.json": payload["retrieval_documents"],
        "policy-bundle.json": payload["policy_bundle"],
        "tool-schemas.json": payload["tool_schemas"],
        "database-fixtures.json": payload["database_fixture"],
        "api-cassettes.json": payload["external_api_cassette"],
        "privacy-map.json": payload["privacy_map"],
        "expected-invariants.json": payload["expected_invariants"],
        "reference-telemetry.json": payload["reference_telemetry"],
        "memory-snapshot.json": payload["memory_snapshot"],
    }
    manifest: dict[str, Any] = {
        "artifacts": {},
        "capsule_digest": capsule.digest,
        "corpus_version": capsule.corpus_version,
        "schema_version": capsule.schema_version,
    }
    paths: list[str] = []
    started = perf_counter()
    with traced(
        "capsule.persist",
        {
            "orbital.signal.class": "campaign",
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.risk.class": "high",
            "orbital.capsule.id": capsule.capsule_id,
            "orbital.capsule.digest": capsule.digest,
            "orbital.capsule.template": capsule.template,
        },
    ):
        try:
            for filename, artifact in artifact_values.items():
                path = versioned_path(
                    "mission-capsules",
                    capsule.capsule_id,
                    sha256_digest(artifact),
                    filename,
                )
                result = objects.put_json(
                    path,
                    "mission_capsule_artifact",
                    capsule.capsule_id,
                    artifact,
                )
                manifest["artifacts"][filename] = {
                    key: result[key]
                    for key in ("path", "checksum", "size_bytes")
                }
                paths.append(path)
            manifest_path = versioned_path(
                "mission-capsules",
                capsule.capsule_id,
                capsule.digest,
                "manifest.json",
            )
            manifest["capsule"] = payload
            manifest_result = objects.put_json(
                manifest_path,
                "mission_capsule",
                capsule.capsule_id,
                manifest,
            )
            paths.append(manifest_path)
        finally:
            persistence_latency.record(
                (perf_counter() - started) * 1000,
                {"orbital.storage.kind": "mission_capsule"},
            )
    with Session(store.engine) as session:
        existing = session.scalar(
            select(CapsuleRecord).where(CapsuleRecord.content_digest == capsule.digest)
        )
        created = existing is None
        if existing and existing.capsule_id != capsule.capsule_id:
            raise HTTPException(409, "capsule digest collision")
        if not existing:
            session.add(
                CapsuleRecord(
                    capsule_id=capsule.capsule_id,
                    content_digest=capsule.digest,
                    schema_version=capsule.schema_version,
                    template=capsule.template,
                    variant=capsule.variant,
                    object_path=manifest_path,
                    checksum=manifest_result["checksum"],
                    artifact_manifest=manifest,
                    created_at=capsule.created_at,
                )
            )
        session.commit()
    store.put(capsule.capsule_id, "mission_capsule", payload, capsule.created_at)
    if persist_file:
        (output_dir / f"{capsule.capsule_id}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return created, paths


@app.post("/v1/capsules/build")
def build(request: BuildRequest) -> dict[str, Any]:
    if request.count_per_template < 1 or request.count_per_template > 10:
        raise HTTPException(422, "count_per_template must be between 1 and 10")
    capsules = [
        build_capsule(template, variant)
        for template in TEMPLATES
        for variant in range(request.count_per_template)
    ]
    output_dir = Path(os.getenv("CAPSULE_OUTPUT_DIR", "missions/baseline"))
    if request.persist_files:
        output_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    object_paths: list[str] = []
    started = perf_counter()
    with traced(
        "capsule.corpus.generate",
        {
            "orbital.signal.class": "campaign",
            "orbital.execution.mode": "deterministic_simulation",
            "orbital.corpus.version": CORPUS_VERSION,
            "orbital.capsule.count": len(capsules),
            "orbital.capsule.template.count": len(TEMPLATES),
            "orbital.risk.class": "high",
        },
    ):
        trace_id, _ = current_trace_ids()
        for capsule in capsules:
            was_created, paths = persist_capsule(
                capsule, request.persist_files, output_dir
            )
            created += int(was_created)
            object_paths.extend(paths)
        duplicates = len(capsules) - created
        capsules_created.add(created)
        capsule_duplicates.add(duplicates)
        corpus_generation_latency.record(
            (perf_counter() - started) * 1000,
            {"orbital.corpus.version": CORPUS_VERSION},
        )
        emit_event(
            "capsule.dataset.persisted",
            corpus_version=CORPUS_VERSION,
            count=len(capsules),
            created=created,
            duplicates=duplicates,
            object_count=len(object_paths),
            trace_id=trace_id,
        )
    return {
        "count": len(capsules),
        "created": created,
        "duplicates": duplicates,
        "corpus_version": CORPUS_VERSION,
        "templates": len(TEMPLATES),
        "variants_per_template": request.count_per_template,
        "dataset_digest": corpus_digest(capsules),
        "capsule_ids": [capsule.capsule_id for capsule in capsules],
        "capsule_digests": [capsule.digest for capsule in capsules],
        "object_paths": object_paths,
        "storage_status": objects.health(),
        "trace_id": trace_id,
    }


@app.get("/v1/capsules/{capsule_id}")
def get_capsule(capsule_id: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        record = session.get(CapsuleRecord, capsule_id)
        if not record:
            raise HTTPException(404, "capsule not found")
        try:
            manifest = objects.get_json(record.object_path, record.checksum)
        except IntegrityError as exc:
            raise HTTPException(409, f"corrupted capsule rejected: {exc}") from exc
        return manifest["capsule"] | {
            "object_path": record.object_path,
            "artifact_manifest": manifest["artifacts"],
        }


@app.get("/v1/capsules")
def list_capsules(limit: int = 120) -> list[dict[str, Any]]:
    with Session(store.engine) as session:
        rows = session.scalars(
            select(CapsuleRecord).order_by(CapsuleRecord.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "capsule_id": row.capsule_id,
                "digest": row.content_digest,
                "template": row.template,
                "variant": row.variant,
                "object_path": row.object_path,
                "checksum": row.checksum,
            }
            for row in rows
        ]


@app.get("/v1/storage/health")
def storage_health() -> dict[str, str]:
    return {"status": objects.health()}
