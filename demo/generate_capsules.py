from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from minio import Minio
from orbital_shared.corpus import (
    CORPUS_VERSION,
    TEMPLATES,
    VARIANTS_PER_TEMPLATE,
    build_corpus,
    corpus_digest,
)
from orbital_shared.models import ReplayMutation
from orbital_shared.range_mutations import (
    DEFAULT_MUTATION_COUNT,
    DEFAULT_MUTATION_SEED,
    MUTATION_CATALOG_VERSION,
    build_mutations,
    category_counts,
    mutation_catalogue_digest,
    operator_counts,
)
from sqlalchemy import create_engine, text

CAPSULE_URL = os.getenv("CAPSULE_BUILDER_URL", "http://capsule-builder:8000").rstrip(
    "/"
)
FOUNDRY_URL = os.getenv(
    "ADVERSARIAL_FOUNDRY_URL", "http://adversarial-foundry:8000"
).rstrip("/")
CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL", "http://orbital-telemetrystore-clickhouse-0-0:8123"
).rstrip("/")
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))
REPORT_PATH = OUTPUT / "phase4a-generation.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Phase 4A corpus verification failed: {message}")


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    expected_status: int = 200,
    timeout: float = 900,
) -> httpx.Response:
    response = httpx.post(url, json=payload, timeout=timeout)
    require(
        response.status_code == expected_status,
        f"{url} returned {response.status_code}: {response.text[:500]}",
    )
    return response


def query_clickhouse(sql: str) -> list[dict[str, Any]]:
    response = httpx.post(
        CLICKHOUSE_URL,
        params={"query": f"{sql} FORMAT JSONEachRow"},
        timeout=30,
    )
    response.raise_for_status()
    return [json.loads(line) for line in response.text.splitlines() if line]


def wait_for_traces(trace_ids: list[str], timeout_seconds: float = 120) -> set[str]:
    expected = {value.lower() for value in trace_ids if value}
    require(len(expected) == len(trace_ids), "one or more trace IDs are absent")
    values = ",".join(f"'{trace_id}'" for trace_id in sorted(expected))
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


def _tampered_payload(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    value["digest"] = ""
    if kind == "invalid":
        value["operator"] = "operator_not_in_catalogue"
    elif kind == "non_reproducible":
        value["mutated_fixture_digest"] = "sha256:" + ("0" * 64)
    else:
        raise ValueError(kind)
    return value


def main() -> None:
    started = time.monotonic()
    expected_capsules = build_corpus()
    expected_capsule_ids = [item.capsule_id for item in expected_capsules]
    expected_capsule_digests = [item.digest for item in expected_capsules]
    require(len(expected_capsules) == 120, "local corpus is not 120 capsules")

    capsule_response = post_json(
        f"{CAPSULE_URL}/v1/capsules/build",
        {
            "count_per_template": VARIANTS_PER_TEMPLATE,
            "persist_files": False,
        },
    ).json()
    require(capsule_response["count"] == 120, "service did not build 120 capsules")
    require(capsule_response["templates"] == 12, "service did not use 12 templates")
    require(
        capsule_response["variants_per_template"] == 10,
        "service did not use ten variants per template",
    )
    require(
        capsule_response["corpus_version"] == CORPUS_VERSION,
        "corpus version mismatch",
    )
    require(
        capsule_response["capsule_ids"] == expected_capsule_ids,
        "capsule IDs are not deterministic",
    )
    require(
        capsule_response["capsule_digests"] == expected_capsule_digests,
        "capsule digests are not deterministic",
    )
    require(
        capsule_response["dataset_digest"] == corpus_digest(expected_capsules),
        "corpus digest mismatch",
    )
    require(
        capsule_response["storage_status"] == "AVAILABLE",
        "capsule storage is unavailable",
    )

    mutation_response = post_json(
        f"{FOUNDRY_URL}/v1/mutations/generate",
        {
            "capsule_ids": capsule_response["capsule_ids"],
            "target_count": DEFAULT_MUTATION_COUNT,
            "seed": DEFAULT_MUTATION_SEED,
        },
    ).json()
    require(mutation_response["count"] == 880, "service did not generate 880 mutations")
    require(mutation_response["rejected"] == 0, "valid catalogue had rejections")
    require(mutation_response["operator_count"] == 42, "operator catalogue is incomplete")
    require(
        mutation_response["catalog_version"] == MUTATION_CATALOG_VERSION,
        "mutation catalogue version mismatch",
    )
    require(
        mutation_response["storage_status"] == "AVAILABLE",
        "mutation storage is unavailable",
    )
    require(
        len(set(mutation_response["mutation_ids"])) == 880,
        "mutation IDs are not unique",
    )
    expected_generated = build_mutations(
        expected_capsules,
        DEFAULT_MUTATION_COUNT,
        DEFAULT_MUTATION_SEED,
    )
    expected_mutations = [item[0] for item in expected_generated]
    expected_mutation_ids = [item.mutation_id for item in expected_mutations]

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as connection:
        capsule_rows = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT capsule_id, content_digest, object_path, checksum, "
                    "artifact_manifest FROM mission_capsules "
                    "WHERE capsule_id = ANY(:capsule_ids) ORDER BY capsule_id"
                ),
                {"capsule_ids": expected_capsule_ids},
            ).mappings()
        ]
        mutation_rows = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT mutation_id, source_capsule_id, category, operator, "
                    "provenance_digest, mutation_digest, mutated_fixture_digest, "
                    "object_path, checksum, valid, reproducible, payload "
                    "FROM replay_mutations "
                    "WHERE mutation_id = ANY(:mutation_ids) ORDER BY sequence"
                ),
                {"mutation_ids": expected_mutation_ids},
            ).mappings()
        ]
    require(len(capsule_rows) == 120, "PostgreSQL capsule corpus is incomplete")
    require(len(mutation_rows) == 880, "PostgreSQL mutation catalogue is incomplete")
    require(
        all(row["valid"] and row["reproducible"] for row in mutation_rows),
        "PostgreSQL contains an invalid or non-reproducible mutation",
    )
    required_artifacts = {
        "user-request.json",
        "agent-artifacts.json",
        "prompt-snapshot.json",
        "retrieval-fixtures.json",
        "policy-bundle.json",
        "tool-schemas.json",
        "database-fixtures.json",
        "api-cassettes.json",
        "privacy-map.json",
        "expected-invariants.json",
        "reference-telemetry.json",
        "memory-snapshot.json",
    }
    for row in capsule_rows:
        manifest = row["artifact_manifest"]
        require(
            set(manifest["artifacts"]) == required_artifacts,
            f"capsule artifact set is incomplete: {row['capsule_id']}",
        )
        require(
            manifest["corpus_version"] == CORPUS_VERSION,
            f"capsule corpus version mismatch: {row['capsule_id']}",
        )

    persisted_mutations = [
        ReplayMutation.model_validate(row["payload"]) for row in mutation_rows
    ]
    require(
        [item.mutation_id for item in persisted_mutations]
        == [item.mutation_id for item in expected_mutations],
        "persisted mutation IDs are not reproducible",
    )
    require(
        [item.digest for item in persisted_mutations]
        == [item.digest for item in expected_mutations],
        "persisted mutation digests are not reproducible",
    )
    require(
        mutation_response["catalogue_digest"]
        == mutation_catalogue_digest(expected_mutations),
        "mutation catalogue digest is not reproducible",
    )
    require(
        mutation_response["categories"] == category_counts(expected_mutations),
        "mutation category counts are incorrect",
    )
    require(
        mutation_response["operators"] == operator_counts(expected_mutations),
        "mutation operator counts are incorrect",
    )
    require(
        all(count >= 20 for count in mutation_response["operators"].values()),
        "one or more mutation operators lack coverage",
    )

    with engine.connect() as connection:
        mutation_count_before_rejection = int(
            connection.scalar(text("SELECT count(*) FROM replay_mutations")) or 0
        )

    first_payload = mutation_rows[0]["payload"]
    invalid_response = post_json(
        f"{FOUNDRY_URL}/v1/mutations/validate",
        {
            "capsule_id": first_payload["source_capsule_id"],
            "mutation": _tampered_payload(first_payload, "invalid"),
        },
        expected_status=422,
    )
    require(
        "rejected" in invalid_response.text.lower(),
        "invalid mutation rejection is not explicit",
    )
    non_reproducible_response = post_json(
        f"{FOUNDRY_URL}/v1/mutations/validate",
        {
            "capsule_id": first_payload["source_capsule_id"],
            "mutation": _tampered_payload(first_payload, "non_reproducible"),
        },
        expected_status=422,
    )
    require(
        "rejected" in non_reproducible_response.text.lower(),
        "non-reproducible mutation rejection is not explicit",
    )

    with engine.connect() as connection:
        mutation_count_after_rejection = int(
            connection.scalar(text("SELECT count(*) FROM replay_mutations")) or 0
        )
        rejection_rows = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT payload FROM orbital_objects "
                    "WHERE kind='mutation_rejection' ORDER BY created_at"
                )
            ).mappings()
        ]
        storage_counts = {
            row["owner_id"]: int(row["object_count"])
            for row in connection.execute(
                text(
                    "SELECT owner_id, count(*) AS object_count FROM storage_objects "
                    "WHERE owner_id = ANY(:owner_ids) GROUP BY owner_id"
                ),
                {
                    "owner_ids": expected_capsule_ids
                    + mutation_response["mutation_ids"]
                },
            ).mappings()
        }
    require(
        mutation_count_after_rejection == mutation_count_before_rejection,
        "rejected mutations were persisted as valid mutations",
    )
    require(
        len(rejection_rows) >= 2,
        "mutation rejection evidence is absent",
    )
    require(
        all(storage_counts.get(capsule_id) == 13 for capsule_id in expected_capsule_ids),
        "one or more capsule bundles are incomplete in MinIO metadata",
    )
    require(
        all(
            storage_counts.get(mutation_id) == 3
            for mutation_id in mutation_response["mutation_ids"]
        ),
        "one or more mutation bundles are incomplete in MinIO metadata",
    )

    minio = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
    for row in capsule_rows + mutation_rows:
        stat = minio.stat_object(bucket, row["object_path"])
        metadata_checksum = stat.metadata.get("x-amz-meta-sha256")
        require(metadata_checksum is not None, f"checksum absent: {row['object_path']}")
        require(
            f"sha256:{metadata_checksum}" == row["checksum"],
            f"checksum mismatch: {row['object_path']}",
        )
        require(bool(stat.version_id), f"version ID absent: {row['object_path']}")

    invalid_rejection = next(
        (
            row["payload"]
            for row in rejection_rows
            if "operator provenance" in row["payload"].get("reason", "")
        ),
        None,
    )
    non_reproducible_rejection = next(
        (
            row["payload"]
            for row in rejection_rows
            if "not reproducible" in row["payload"].get("reason", "")
        ),
        None,
    )
    require(invalid_rejection is not None, "invalid-operator rejection row is absent")
    require(
        non_reproducible_rejection is not None,
        "non-reproducible rejection row is absent",
    )
    rejection_trace_ids = [
        invalid_rejection["trace_id"],
        non_reproducible_rejection["trace_id"],
    ]
    trace_ids = [
        capsule_response["trace_id"],
        mutation_response["trace_id"],
        *rejection_trace_ids,
    ]
    found_trace_ids = wait_for_traces(trace_ids)
    require(
        set(trace_ids) <= found_trace_ids,
        "SigNoz is missing Phase 4A generation or rejection traces",
    )

    report = {
        "status": "PASS",
        "phase": "4A",
        "execution_mode": "deterministic_simulation",
        "corpus": {
            "version": CORPUS_VERSION,
            "templates": len(TEMPLATES),
            "variants_per_template": VARIANTS_PER_TEMPLATE,
            "capsules": len(expected_capsules),
            "dataset_digest": capsule_response["dataset_digest"],
            "created": capsule_response["created"],
            "duplicates": capsule_response["duplicates"],
        },
        "mutations": {
            "catalog_version": MUTATION_CATALOG_VERSION,
            "count": mutation_response["count"],
            "created": mutation_response["created"],
            "duplicates": mutation_response["duplicates"],
            "rejected_from_valid_catalogue": mutation_response["rejected"],
            "catalogue_digest": mutation_response["catalogue_digest"],
            "categories": mutation_response["categories"],
            "operator_count": mutation_response["operator_count"],
            "operator_coverage_minimum": min(mutation_response["operators"].values()),
        },
        "rejection_tests": {
            "invalid_operator": "REJECTED",
            "non_reproducible_digest": "REJECTED",
            "canonical_valid_mutations_after_rejection": len(mutation_rows),
            "all_phase_mutations_before_rejection": mutation_count_before_rejection,
            "all_phase_mutations_after_rejection": mutation_count_after_rejection,
            "write_count_unchanged": (
                mutation_count_after_rejection == mutation_count_before_rejection
            ),
        },
        "persistence": {
            "postgres_capsules": len(capsule_rows),
            "postgres_mutations": len(mutation_rows),
            "capsule_objects": sum(
                storage_counts[item] for item in expected_capsule_ids
            ),
            "mutation_objects": sum(
                storage_counts[item] for item in mutation_response["mutation_ids"]
            ),
            "minio_manifest_checks": len(capsule_rows) + len(mutation_rows),
        },
        "signoz_trace_ids": trace_ids,
        "duration_seconds": round(time.monotonic() - started, 3),
        "deferred": [
            "adaptive_attack_selection",
            "metamorphic_testing",
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
