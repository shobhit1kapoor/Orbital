from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from minio import Minio
from sqlalchemy import create_engine, text

CAUSAL_URL = os.getenv("CAUSAL_ENGINE_URL", "http://causal-engine:8000").rstrip(
    "/"
)
CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL", "http://orbital-telemetrystore-clickhouse-0-0:8123"
).rstrip("/")
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))
ANALYSIS_STATE = OUTPUT / "phase4c-analysis-state.json"
MINIMIZATION_STATE = OUTPUT / "phase4c-minimization-state.json"
REPORT_PATH = OUTPUT / "phase4c-validation.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Phase 4C verification failed: {message}")


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 60,
) -> dict[str, Any]:
    response = httpx.request(
        method,
        f"{CAUSAL_URL}{path}",
        json=payload,
        timeout=timeout,
    )
    require(
        response.is_success,
        f"{path} returned {response.status_code}: {response.text[:500]}",
    )
    return response.json()


def wait_for(path: str, terminal: set[str], timeout_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = request_json("GET", path)
        if last["status"] in terminal:
            return last
        time.sleep(1)
    raise SystemExit(f"Phase 4C job did not terminate: {last}")


def query_clickhouse(sql: str) -> list[dict[str, Any]]:
    response = httpx.post(
        CLICKHOUSE_URL,
        params={"query": f"{sql} FORMAT JSONEachRow"},
        timeout=30,
    )
    response.raise_for_status()
    return [json.loads(line) for line in response.text.splitlines() if line]


def wait_for_traces(trace_ids: list[str], timeout_seconds: float = 120) -> set[str]:
    expected = {item.lower() for item in trace_ids if item}
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


def analyze() -> dict[str, Any]:
    started = time.monotonic()
    launch = request_json(
        "POST",
        "/v1/causal/analyze",
        {
            "repeat_count": 16,
            "shapley_samples": 64,
            "bootstrap_samples": 500,
            "seed": 20260723,
            "model_parameters": {
                "model_identifier": "qwen3:8b",
                "temperature": 0,
                "context_window": 8192,
                "maximum_output_tokens": 1024,
                "execution_mode": "deterministic_simulation",
            },
        },
    )
    analysis_id = launch["analysis_id"]
    final = wait_for(
        f"/v1/causal/analyses/{analysis_id}",
        {"COMPLETED"},
        600,
    )
    finding = final["result"]
    require(final["verdict"] == "CONFIRMED", "causal verdict is not CONFIRMED")
    require(final["expected_branches"] == 256, "branch budget is not 256")
    require(final["completed_branches"] == 256, "counterfactual branches are incomplete")
    require(len(finding["single_effects"]) == 5, "single-factor coverage is incomplete")
    require(len(finding["pairwise_effects"]) == 10, "pairwise coverage is incomplete")
    require(
        finding["earliest_commitment_point"] == "prompt_compression",
        "earliest commitment point is incorrect",
    )
    require(finding["shapley_samples"] == 64, "attribution sample bound changed")
    require(
        abs(sum(item["contribution"] for item in finding["attribution"]) - 1) < 1e-5,
        "causal attribution is not normalized",
    )
    require(
        all(
            item["confidence_low"]
            <= item["contribution"]
            <= item["confidence_high"]
            for item in finding["single_effects"] + finding["pairwise_effects"]
        ),
        "one or more confidence intervals are invalid",
    )
    state = {
        "analysis_id": analysis_id,
        "launch": launch,
        "final": final,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ANALYSIS_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps(state, indent=2))
    return state


def minimize() -> dict[str, Any]:
    require(ANALYSIS_STATE.exists(), "causal analysis state is absent")
    analysis = json.loads(ANALYSIS_STATE.read_text(encoding="utf-8"))
    started = time.monotonic()
    launch = request_json(
        "POST",
        "/v1/causal/minimize",
        {
            "analysis_id": analysis["analysis_id"],
            "timebox_seconds": 10_800,
        },
    )
    minimization_id = launch["minimization_id"]
    final = wait_for(
        f"/v1/causal/minimizations/{minimization_id}",
        {"COMPLETED", "LIMITATION"},
        180,
    )
    require(final["status"] == "COMPLETED", "bounded hero minimizer did not complete")
    result = final["result"]
    require(result["verdict"] == "CONFIRMED", "minimized failure is not verified")
    require(
        result["minimized_size"] < result["original_size"],
        "hero fixture was not reduced",
    )
    require(result["attempt_count"] > 0, "reduction attempts were not recorded")
    require(
        set(result["retained_causal_factors"])
        == {
            "prompt_compression",
            "stale_retrieval",
            "tool_schema_change",
            "deterministic_authorization",
            "final_tool_execution",
        },
        "minimized capsule lost a retained causal factor",
    )
    regression_path = Path(final["regression_path"])
    require(regression_path.exists(), "regression capsule file is absent")
    regression = json.loads(regression_path.read_text(encoding="utf-8"))
    require(
        regression["failure_signature"] == result["failure_signature"],
        "regression capsule does not preserve the verified failure",
    )
    state = {
        "minimization_id": minimization_id,
        "launch": launch,
        "final": final,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    MINIMIZATION_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps(state, indent=2))
    return state


def verify() -> dict[str, Any]:
    require(ANALYSIS_STATE.exists(), "causal analysis state is absent")
    require(MINIMIZATION_STATE.exists(), "hero minimization state is absent")
    analysis_state = json.loads(ANALYSIS_STATE.read_text(encoding="utf-8"))
    minimization_state = json.loads(
        MINIMIZATION_STATE.read_text(encoding="utf-8")
    )
    analysis_id = analysis_state["analysis_id"]
    minimization_id = minimization_state["minimization_id"]
    analysis = request_json("GET", f"/v1/causal/analyses/{analysis_id}")
    minimization = request_json(
        "GET", f"/v1/causal/minimizations/{minimization_id}"
    )
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as connection:
        branches = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT branch_id, interventions, branch_kind, seed, "
                    "model_parameters, trace_id, status, delivery_count, "
                    "result_digest, object_path, checksum "
                    "FROM causal_branches WHERE analysis_id=:id "
                    "ORDER BY branch_kind, intervention_digest, repeat_index"
                ),
                {"id": analysis_id},
            ).mappings()
        ]
        attempts = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT attempt_id, sequence, category, removed_ids, "
                    "candidate_size, failure_preserved, result_signature "
                    "FROM hero_minimization_attempts WHERE minimization_id=:id "
                    "ORDER BY sequence"
                ),
                {"id": minimization_id},
            ).mappings()
        ]
        storage_count = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM storage_objects "
                    "WHERE owner_id IN (:analysis_id, :minimization_id)"
                ),
                {
                    "analysis_id": analysis_id,
                    "minimization_id": minimization_id,
                },
            )
            or 0
        )
    require(len(branches) == 256, "PostgreSQL causal branches are incomplete")
    require(
        all(row["status"] == "COMPLETED" for row in branches),
        "PostgreSQL contains an incomplete causal branch",
    )
    require(len({row["seed"] for row in branches}) == 16, "seed set is incomplete")
    require(
        len({json.dumps(row["interventions"]) for row in branches}) == 16,
        "intervention-set coverage is incomplete",
    )
    require(
        all(row["model_parameters"]["temperature"] == 0 for row in branches),
        "model parameters were not persisted",
    )
    require(
        len(attempts) == minimization["attempt_count"] > 0,
        "reduction-attempt persistence is incomplete",
    )
    require(storage_count >= 259, "MinIO metadata is incomplete")

    minio = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
    paths = [
        analysis["object_path"],
        minimization["object_path"],
        minimization["result"]["attempts_object_path"],
        minimization["result"]["regression_object_path"],
        *[item["object_path"] for item in branches[:5] + branches[-5:]],
    ]
    for path in paths:
        stat = minio.stat_object(bucket, path)
        require(
            bool(stat.metadata.get("x-amz-meta-sha256")),
            f"MinIO checksum metadata is absent: {path}",
        )

    retry_branch = branches[0]
    request_json(
        "POST",
        f"/v1/causal/analyses/{analysis_id}/branches/"
        f"{retry_branch['branch_id']}/redeliver",
    )
    request_json(
        "POST",
        f"/v1/causal/minimizations/{minimization_id}/redeliver",
    )
    deadline = time.monotonic() + 60
    redelivered_branch = None
    redelivered_minimization = None
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            redelivered_branch = dict(
                connection.execute(
                    text(
                        "SELECT delivery_count, result_digest FROM causal_branches "
                        "WHERE branch_id=:id"
                    ),
                    {"id": retry_branch["branch_id"]},
                ).mappings().one()
            )
            redelivered_minimization = dict(
                connection.execute(
                    text(
                        "SELECT delivery_count, result_digest "
                        "FROM hero_minimizations WHERE minimization_id=:id"
                    ),
                    {"id": minimization_id},
                ).mappings().one()
            )
        if (
            redelivered_branch["delivery_count"]
            > retry_branch["delivery_count"]
            and redelivered_minimization["delivery_count"]
            > minimization["delivery_count"]
        ):
            break
        time.sleep(1)
    require(
        redelivered_branch["result_digest"] == retry_branch["result_digest"],
        "duplicate branch delivery changed its result",
    )
    require(
        redelivered_minimization["result_digest"]
        == minimization["result_digest"],
        "duplicate minimization delivery changed its result",
    )

    unknown = request_json(
        "POST",
        "/v1/causal/analyze",
        {
            "source_mutation_id": "missing-local-evidence",
            "repeat_count": 8,
            "shapley_samples": 8,
            "bootstrap_samples": 100,
            "seed": 7,
        },
    )
    require(
        unknown["status"] == "COMPLETED" and unknown["verdict"] == "UNKNOWN",
        "missing evidence did not produce UNKNOWN",
    )
    require(unknown["expected_branches"] == 0, "UNKNOWN analysis created branches")

    trace_ids = [
        analysis["trace_id"],
        analysis["result"]["completion_trace_id"],
        minimization["result"]["trace_id"],
        *[row["trace_id"] for row in branches[:5] + branches[-5:]],
    ]
    found = wait_for_traces(trace_ids)
    require(set(trace_ids) <= found, "SigNoz causal trace evidence is incomplete")
    report = {
        "status": "PASS",
        "phase": "4C",
        "execution_mode": "counterfactual_and_deterministic_simulation",
        "analysis_id": analysis_id,
        "source_mutation_id": analysis["source_mutation_id"],
        "source_branch_id": analysis["source_branch_id"],
        "causal_branches": len(branches),
        "single_interventions": 5,
        "pairwise_interventions": 10,
        "repeat_count": analysis["config"]["repeat_count"],
        "shapley_samples": analysis["result"]["shapley_samples"],
        "earliest_commitment_point": analysis["result"][
            "earliest_commitment_point"
        ],
        "finding_digest": analysis["finding_digest"],
        "minimization_id": minimization_id,
        "reduction_attempts": len(attempts),
        "original_size": minimization["result"]["original_size"],
        "minimized_size": minimization["result"]["minimized_size"],
        "retained_causal_factors": minimization["result"][
            "retained_causal_factors"
        ],
        "regression_path": minimization["regression_path"],
        "unknown_on_missing_evidence": True,
        "idempotent_redelivery": True,
        "minio_paths_sample": paths,
        "signoz_trace_ids": trace_ids,
        "limitations": [
            "one bounded primary refund reliability fixture only",
            "attribution uses 64 deterministic local samples",
            "no general minimization platform",
        ],
        "deferred": [
            "FRONTIER",
            "CLEARANCE",
            "multi_agent_custody",
            "Mission_Control",
            "final_submission",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["analyze", "minimize", "verify"])
    args = parser.parse_args()
    if args.phase == "analyze":
        analyze()
    elif args.phase == "minimize":
        minimize()
    else:
        verify()


if __name__ == "__main__":
    main()
