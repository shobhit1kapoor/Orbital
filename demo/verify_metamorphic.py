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
REPORT_PATH = OUTPUT / "phase4b-metamorphic.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Phase 4B metamorphic verification failed: {message}")


def request_json(method: str, path: str, payload: dict[str, Any] | None = None):
    response = httpx.request(
        method, f"{REPLAY_URL}{path}", json=payload, timeout=60
    )
    require(
        response.is_success,
        f"{path} returned {response.status_code}: {response.text[:500]}",
    )
    return response.json()


def wait_for_suite(suite_id: str, timeout_seconds: float = 180):
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = request_json("GET", f"/v1/metamorphic/suites/{suite_id}")
        if last["status"] == "COMPLETED":
            return last
        time.sleep(1)
    raise SystemExit(f"metamorphic suite did not complete: {last}")


def query_clickhouse(sql: str) -> list[dict[str, Any]]:
    response = httpx.post(
        CLICKHOUSE_URL,
        params={"query": f"{sql} FORMAT JSONEachRow"},
        timeout=30,
    )
    response.raise_for_status()
    return [json.loads(line) for line in response.text.splitlines() if line]


def wait_for_traces(trace_ids: list[str], timeout_seconds: float = 120) -> set[str]:
    expected = {item.lower() for item in trace_ids}
    values = ",".join(f"'{item}'" for item in sorted(expected))
    deadline = time.monotonic() + timeout_seconds
    found: set[str] = set()
    while time.monotonic() < deadline:
        rows = query_clickhouse(
            "SELECT DISTINCT trace_id AS trace_id "
            "FROM signoz_traces.distributed_signoz_index_v3 "
            f"WHERE trace_id IN ({values})"
        )
        found = {str(row["trace_id"]).lower() for row in rows}
        if expected <= found:
            return found
        time.sleep(2)
    return found


def main() -> None:
    started = time.monotonic()
    launch = request_json(
        "POST",
        "/v1/metamorphic/suites",
        {"submission_key": "phase4b-metamorphic-v1"},
    )
    suite_id = launch["suite_id"]
    final = wait_for_suite(suite_id)
    require(final["case_count"] == 9, "not every specified invariant was evaluated")
    require(final["completed"] == 9, "one or more invariant cases are incomplete")
    require(final["passed"] == 9 and final["failed"] == 0, "an invariant failure occurred")
    require(
        len({item["invariant"] for item in final["cases"]}) == 9,
        "invariant coverage contains duplicates",
    )

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT case_id, invariant, trace_id, status, delivery_count, "
                    "result_payload, result_digest, object_path, checksum "
                    "FROM metamorphic_cases WHERE suite_id=:id ORDER BY invariant"
                ),
                {"id": suite_id},
            ).mappings()
        ]
    require(len(rows) == 9, "PostgreSQL metamorphic records are incomplete")
    require(
        all(row["status"] == "COMPLETED" for row in rows),
        "PostgreSQL contains an incomplete invariant case",
    )
    require(
        all((row["result_payload"] or {}).get("passed") for row in rows),
        "PostgreSQL contains an invariant failure",
    )

    minio = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
    for row in rows:
        stat = minio.stat_object(bucket, row["object_path"])
        metadata = stat.metadata.get("x-amz-meta-sha256")
        require(metadata is not None, f"MinIO checksum absent: {row['object_path']}")
        require(
            f"sha256:{metadata}" == row["checksum"],
            f"MinIO checksum mismatch: {row['object_path']}",
        )

    retry_case = rows[0]
    request_json("POST", f"/v1/metamorphic/cases/{retry_case['case_id']}/redeliver")
    deadline = time.monotonic() + 60
    redelivered = None
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            redelivered = dict(
                connection.execute(
                    text(
                        "SELECT delivery_count, result_digest FROM metamorphic_cases "
                        "WHERE case_id=:id"
                    ),
                    {"id": retry_case["case_id"]},
                ).mappings().one()
            )
        if redelivered["delivery_count"] > retry_case["delivery_count"]:
            break
        time.sleep(1)
    require(
        redelivered is not None
        and redelivered["delivery_count"] > retry_case["delivery_count"],
        "duplicate invariant delivery was not observed",
    )
    require(
        redelivered["result_digest"] == retry_case["result_digest"],
        "duplicate invariant delivery changed the result",
    )

    duplicate = request_json(
        "POST",
        "/v1/metamorphic/suites",
        {"submission_key": "phase4b-metamorphic-v1"},
    )
    require(
        duplicate["duplicate_submission"] is True,
        "duplicate suite submission was not deduplicated",
    )
    trace_ids = [launch["trace_id"]] + [
        (row["result_payload"] or {}).get("trace_id", row["trace_id"]) for row in rows
    ]
    found = wait_for_traces(trace_ids)
    require(set(trace_ids) <= found, "SigNoz is missing invariant-evaluation traces")

    report = {
        "status": "PASS",
        "phase": "4B-METAMORPHIC",
        "execution_mode": "deterministic_simulation",
        "suite_id": suite_id,
        "invariants_evaluated": len(rows),
        "passed": final["passed"],
        "failed": final["failed"],
        "idempotent_redelivery": True,
        "postgres_records": len(rows),
        "minio_paths": [row["object_path"] for row in rows],
        "signoz_trace_ids": trace_ids,
        "duration_seconds": round(time.monotonic() - started, 3),
        "out_of_scope": [
            "causal_analysis",
            "shapley_attribution",
            "mission_minimization",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
