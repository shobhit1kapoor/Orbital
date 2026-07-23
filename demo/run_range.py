from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from minio import Minio
from sqlalchemy import create_engine, text

FOUNDRY_URL = os.getenv(
    "ADVERSARIAL_FOUNDRY_URL", "http://adversarial-foundry:8000"
).rstrip("/")
CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL", "http://orbital-telemetrystore-clickhouse-0-0:8123"
).rstrip("/")
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))
REPORT_PATH = OUTPUT / "phase4b-range.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Phase 4B RANGE verification failed: {message}")


def request_json(method: str, path: str, payload: dict[str, Any] | None = None):
    response = httpx.request(
        method,
        f"{FOUNDRY_URL}{path}",
        json=payload,
        timeout=60,
    )
    require(
        response.is_success,
        f"{path} returned {response.status_code}: {response.text[:500]}",
    )
    return response.json()


def wait_for_campaign(campaign_id: str, timeout_seconds: float = 900):
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = request_json("GET", f"/v1/attacks/adapt/{campaign_id}")
        if last["status"] in {"COMPLETED", "PARTIAL", "FAILED"}:
            return last
        time.sleep(2)
    raise SystemExit(f"adaptive safety-test campaign did not terminate: {last}")


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
        "/v1/attacks/adapt",
        {
            "top_k": 64,
            "beam_width": 4,
            "generations": 5,
            "force_deterministic_fallback": True,
        },
    )
    campaign_id = launch["campaign_id"]
    final = wait_for_campaign(campaign_id)
    require(final["status"] == "COMPLETED", "campaign did not complete")
    require(launch["selected_count"] == 64, "top-64 selection is incomplete")
    require(
        launch["search"]["beam_width"] == 4
        and launch["search"]["generations"] == 5,
        "adaptive limits changed",
    )
    require(launch["search"]["budget"] == 1280, "search budget is not 1,280")
    require(
        final["search"]["budget_used"] == final["search"]["budget"] == 1280,
        "recorded search budget and completed work differ",
    )
    require(
        final["search"]["proposal_source"] == "deterministic_fallback",
        "execution was not labeled as deterministic fallback",
    )

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as connection:
        scores = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT mutation_id, rank, selected, total_score, factors, "
                    "provenance, score_digest FROM range_mutation_scores "
                    "WHERE campaign_id=:id ORDER BY total_score DESC, mutation_id"
                ),
                {"id": campaign_id},
            ).mappings()
        ]
        branches = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT branch_id, seed_mutation_id, generation, beam_index, "
                    "trace_id, status, delivery_count, result_digest, object_path, "
                    "checksum FROM range_adaptive_branches "
                    "WHERE campaign_id=:id ORDER BY seed_mutation_id, beam_index, generation"
                ),
                {"id": campaign_id},
            ).mappings()
        ]
    require(len(scores) == 880, "PostgreSQL does not contain all 880 scores")
    selected = [item for item in scores if item["selected"]]
    require(len(selected) == 64, "PostgreSQL top-64 selection is incomplete")
    require(
        [item["rank"] for item in selected] == list(range(1, 65)),
        "selection ranks are not complete and deterministic",
    )
    require(
        all(len(item["factors"]) == 6 for item in scores),
        "a safety mutation lacks one or more scoring factors",
    )
    require(len(branches) == 1280, "Celery branch count is not 1,280")
    require(
        all(item["status"] == "COMPLETED" for item in branches),
        "one or more adaptive test-case branches are incomplete",
    )
    require(
        {(item["generation"], item["beam_index"]) for item in branches}
        == {(generation, beam) for generation in range(1, 6) for beam in range(4)},
        "beam or generation coverage is incomplete",
    )
    require(
        all(
            item["result_digest"] and item["object_path"] and item["checksum"]
            for item in branches
        ),
        "adaptive persistence metadata is incomplete",
    )

    minio = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
    selection_stat = minio.stat_object(bucket, launch["selection_object_path"])
    require(
        bool(selection_stat.metadata.get("x-amz-meta-sha256")),
        "selection provenance checksum is absent in MinIO",
    )
    sample = branches[:5] + branches[-5:]
    for row in sample:
        stat = minio.stat_object(bucket, row["object_path"])
        metadata = stat.metadata.get("x-amz-meta-sha256")
        require(metadata is not None, f"MinIO checksum absent: {row['object_path']}")
        require(
            f"sha256:{metadata}" == row["checksum"],
            f"MinIO checksum mismatch: {row['object_path']}",
        )

    duplicate = request_json(
        "POST",
        "/v1/attacks/adapt",
        {
            "top_k": 64,
            "beam_width": 4,
            "generations": 5,
            "force_deterministic_fallback": True,
        },
    )
    require(duplicate["duplicate_submission"] is True, "duplicate run was not deduplicated")
    retry_branch = branches[0]
    request_json(
        "POST",
        f"/v1/attacks/adapt/{campaign_id}/branches/{retry_branch['branch_id']}/redeliver",
    )
    deadline = time.monotonic() + 60
    redelivered = None
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            redelivered = dict(
                connection.execute(
                    text(
                        "SELECT delivery_count, result_digest FROM range_adaptive_branches "
                        "WHERE branch_id=:id"
                    ),
                    {"id": retry_branch["branch_id"]},
                ).mappings().one()
            )
        if redelivered["delivery_count"] > retry_branch["delivery_count"]:
            break
        time.sleep(1)
    require(
        redelivered is not None
        and redelivered["delivery_count"] > retry_branch["delivery_count"],
        "duplicate Celery delivery was not observed",
    )
    require(
        redelivered["result_digest"] == retry_branch["result_digest"],
        "duplicate delivery changed the persisted result",
    )

    trace_ids = [launch["trace_id"]] + [item["trace_id"] for item in sample]
    found = wait_for_traces(trace_ids)
    require(set(trace_ids) <= found, "SigNoz is missing selection or adaptation traces")
    report = {
        "status": "PASS",
        "phase": "4B-RANGE",
        "execution_mode": "deterministic_simulation",
        "campaign_id": campaign_id,
        "safety_mutations_scored": len(scores),
        "selected_test_cases": len(selected),
        "adaptive_branches": len(branches),
        "beam_width": 4,
        "maximum_generations": 5,
        "search_budget": 1280,
        "selection_digest": final["selection_digest"],
        "selection_object_path": launch["selection_object_path"],
        "proposal_source": final["search"]["proposal_source"],
        "idempotent_redelivery": True,
        "minio_paths_sample": [item["object_path"] for item in sample],
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
