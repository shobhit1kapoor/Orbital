from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from minio import Minio
from sqlalchemy import create_engine, text

REPLAY_URL = os.getenv(
    "REPLAY_ORCHESTRATOR_URL", "http://replay-orchestrator:8000"
).rstrip("/")
CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL", "http://orbital-telemetrystore-clickhouse-0-0:8123"
).rstrip("/")
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))
STATE_PATH = OUTPUT / "phase3-campaign.json"
REPORT_PATH = OUTPUT / "phase3-validation.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Persistent campaign verification failed: {message}")


def get_json(path: str) -> dict[str, Any]:
    response = httpx.get(f"{REPLAY_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def wait_for_completion(campaign_id: str, timeout_seconds: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = get_json(f"/v1/campaigns/{campaign_id}")
        if last["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return last
        time.sleep(1)
    raise SystemExit(f"campaign did not terminate: {last}")


def query_clickhouse(sql: str) -> list[dict[str, Any]]:
    response = httpx.post(
        CLICKHOUSE_URL,
        params={"query": f"{sql} FORMAT JSONEachRow"},
        timeout=30,
    )
    response.raise_for_status()
    return [json.loads(line) for line in response.text.splitlines() if line]


def wait_for_traces(trace_ids: list[str], timeout_seconds: float = 90) -> set[str]:
    deadline = time.monotonic() + timeout_seconds
    values = ",".join(f"'{trace_id}'" for trace_id in trace_ids)
    while time.monotonic() < deadline:
        rows = query_clickhouse(
            "SELECT DISTINCT trace_id AS trace_id "
            "FROM signoz_traces.distributed_signoz_index_v3 "
            f"WHERE trace_id IN ({values})"
        )
        found = {str(row["trace_id"]).lower() for row in rows}
        if set(trace_ids) <= found:
            return found
        time.sleep(2)
    return found


def sse_events(campaign_id: str, after: int = 0) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{REPLAY_URL}/v1/campaigns/{campaign_id}/events",
        params={"after": after, "once": "true"},
        timeout=30,
    )
    response.raise_for_status()
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def main() -> None:
    started = time.monotonic()
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    campaign_id = state["campaign_id"]
    campaign = wait_for_completion(campaign_id)
    require(campaign["status"] == "COMPLETED", "campaign is not COMPLETED")
    counts = campaign["counts"]
    require(counts["total"] == 24, "unexpected replay-job count")
    require(counts["completed"] == counts["total"], "Celery jobs did not all complete")
    require(counts["failed"] == 0, "one or more replay jobs remain failed")
    require(counts["retried"] >= 2, "deterministic retry jobs were not observed")
    require(state.get("duplicate_submission") is True, "duplicate submission proof is absent")
    require(state.get("storage_unavailable_observed") is True, "MinIO outage proof is absent")

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as connection:
        db_counts = dict(
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM campaigns) campaigns, "
                    "(SELECT count(*) FROM replay_jobs WHERE campaign_id=:id) replay_jobs, "
                    "(SELECT count(*) FROM mission_capsules) capsules, "
                    "(SELECT count(*) FROM storage_objects) storage_objects, "
                    "(SELECT count(*) FROM orbital_objects "
                    " WHERE kind='replay_effect_receipt' "
                    " AND object_id IN "
                    " (SELECT 'replay-effect:' || job_id FROM replay_jobs "
                    "  WHERE campaign_id=:id)) receipts"
                ),
                {"id": campaign_id},
            ).mappings().one()
        )
        events = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT sequence, event_type, payload FROM campaign_events "
                    "WHERE campaign_id=:id ORDER BY sequence"
                ),
                {"id": campaign_id},
            ).mappings()
        ]
        storage_rows = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT object_path, checksum, kind FROM storage_objects "
                    "WHERE owner_id=:id OR kind IN "
                    "('mission_capsule','mission_capsule_artifact','mutation_artifact') "
                    "ORDER BY object_path"
                ),
                {"id": campaign_id},
            ).mappings()
        ]
    require(db_counts["campaigns"] >= 1, "PostgreSQL campaign metadata is absent")
    require(db_counts["replay_jobs"] == 24, "PostgreSQL replay jobs are incomplete")
    require(db_counts["capsules"] >= 12, "PostgreSQL capsule metadata is incomplete")
    require(db_counts["receipts"] == 24, "effect receipts are missing or duplicated")

    event_types = {event["event_type"] for event in events}
    for required in {
        "campaign.created",
        "campaign.paused",
        "campaign.resumed",
        "campaign.recovered",
        "job.retry",
        "job.completed",
        "campaign.chord.completed",
    }:
        require(required in event_types, f"lifecycle event is missing: {required}")

    minio = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
    verified_paths: list[str] = []
    for row in storage_rows:
        stat = minio.stat_object(bucket, row["object_path"])
        metadata_checksum = stat.metadata.get("x-amz-meta-sha256")
        require(metadata_checksum is not None, f"checksum metadata absent: {row['object_path']}")
        require(
            f"sha256:{metadata_checksum}" == row["checksum"],
            f"checksum mismatch: {row['object_path']}",
        )
        require(bool(stat.version_id), f"MinIO version ID absent: {row['object_path']}")
        verified_paths.append(row["object_path"])
    required_prefixes = {
        "mission-capsules/v1/",
        "mutation-artifacts/v1/",
        "replay-branches/v1/",
        "campaign-exports/v1/",
    }
    for prefix in required_prefixes:
        require(
            any(path.startswith(prefix) for path in verified_paths),
            f"missing {prefix} objects",
        )

    all_sse = sse_events(campaign_id, 0)
    require(all_sse, "SSE returned no persisted progress")
    cursor = int(all_sse[len(all_sse) // 2]["sequence"])
    reconnected = sse_events(campaign_id, cursor)
    require(reconnected, "SSE reconnection returned no remaining progress")
    require(
        all(int(event["sequence"]) > cursor for event in reconnected),
        "SSE reconnection replayed acknowledged events",
    )
    progress_events = [event for event in reconnected if event.get("counts")]
    require(
        progress_events
        and max(event["counts"].get("completed", 0) for event in progress_events) == 24,
        "SSE progress never reached complete",
    )

    retry_job = next(job for job in campaign["jobs"] if job["retries"] > 0)
    response = httpx.post(
        f"{REPLAY_URL}/v1/jobs/{retry_job['job_id']}/redeliver",
        timeout=60,
    )
    response.raise_for_status()
    redelivery = response.json()
    require(redelivery["idempotent"] is True, "duplicate task delivery changed the result")
    require(
        redelivery["result"].get("idempotent_replay") is True,
        "worker did not identify duplicate delivery",
    )
    with engine.connect() as connection:
        receipt_count = connection.scalar(
            text(
                "SELECT count(*) FROM orbital_objects "
                "WHERE object_id=:receipt AND kind='replay_effect_receipt'"
            ),
            {"receipt": f"replay-effect:{retry_job['job_id']}"},
        )
    require(receipt_count == 1, "duplicate task delivery duplicated an effect receipt")

    trace_ids = [job["trace_id"] for job in campaign["jobs"]]
    found_trace_ids = wait_for_traces(trace_ids)
    require(set(trace_ids) <= found_trace_ids, "SigNoz is missing replay job traces")

    report = {
        "status": "PASS",
        "campaign_id": campaign_id,
        "campaign_status": campaign["status"],
        "campaign_counts": counts,
        "database_counts": db_counts,
        "recovery_tests": [
            "pause_resume",
            "redis_restart",
            "celery_worker_restart",
            "fastapi_restart",
            "postgresql_restart",
            "minio_unavailable_and_restart",
            "campaign_recovery",
            "duplicate_task_delivery",
            "sse_reconnection",
        ],
        "minio_object_paths": verified_paths,
        "signoz_trace_ids": trace_ids,
        "event_count": len(events),
        "sse_event_count": len(all_sse),
        "duration_seconds": round(time.monotonic() - started, 3),
        "limitations": [
            "Replay outcomes are labeled deterministic_simulation.",
            "The campaign uses only synthetic local capsules and mutation fixtures.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            report
            | {
                "minio_object_paths": {
                    "count": len(verified_paths),
                    "examples": verified_paths[:8],
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
