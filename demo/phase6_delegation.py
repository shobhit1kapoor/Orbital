from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from minio import Minio
from orbital_shared.database import (
    CertificationRecord,
    DelegationEventRecord,
    DelegationEvidenceRecord,
    ObjectStore,
    Session,
)
from orbital_shared.models import FlightCertificate, sha256_digest
from sqlalchemy import func, select, text

AGENT_RUNTIME_URL = os.getenv("AGENT_RUNTIME_URL", "http://agent-runtime:8000").rstrip("/")
CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL",
    "http://orbital-telemetrystore-clickhouse-0-0:8123",
)
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "/workspace/data/demo-output"))
DEMO_STATE = OUTPUT / "phase6-delegation.json"
VALIDATION_STATE = OUTPUT / "phase6-validation.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def request_json(method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.request(
        method,
        f"{AGENT_RUNTIME_URL}{path}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def query_clickhouse(sql: str) -> list[dict[str, Any]]:
    response = httpx.post(
        CLICKHOUSE_URL,
        params={"query": f"{sql} FORMAT JSONEachRow"},
        timeout=30,
    )
    response.raise_for_status()
    return [json.loads(line) for line in response.text.splitlines() if line]


def wait_for_trace(trace_id: str, timeout_seconds: float = 120) -> set[str]:
    deadline = time.monotonic() + timeout_seconds
    names: set[str] = set()
    while time.monotonic() < deadline:
        rows = query_clickhouse(
            "SELECT DISTINCT name FROM signoz_traces.distributed_signoz_index_v3 "
            f"WHERE trace_id='{trace_id}'"
        )
        names = {str(row["name"]) for row in rows}
        if {"agent.delegate", "policy.authorize", "capability.issue"} <= names:
            return names
        time.sleep(2)
    return names


def _certificate_for(
    session: Session,
    *,
    candidate_id: str | None = None,
    verdict: str | None = None,
) -> FlightCertificate:
    query = select(CertificationRecord).order_by(CertificationRecord.created_at.desc())
    if candidate_id:
        query = query.where(CertificationRecord.candidate_id == candidate_id)
    if verdict:
        query = query.where(CertificationRecord.verdict == verdict)
    record = session.scalar(query.limit(1))
    if record is None:
        raise RuntimeError(
            "Phase 5 certificate evidence is missing; Phase 6 requires the "
            "completed Phase 5 checkpoint"
        )
    return FlightCertificate.model_validate(record.certificate_payload["certificate"])


def delegation_payload() -> dict[str, Any]:
    store = ObjectStore()
    with Session(store.engine) as session:
        parent = _certificate_for(session, candidate_id="candidate-v2-fixed")
        child = _certificate_for(session, candidate_id="candidate-phase5-go", verdict="GO")
    stable = sha256_digest(
        [parent.certificate_id, child.certificate_id, "phase6-authority-laundering"]
    ).removeprefix("sha256:")
    expiration = min(parent.expires_at, child.expires_at)
    return {
        "schema_version": "orbital.delegation/v1",
        "delegation_id": f"dlg_{stable[:20]}",
        "mission_id": f"mis_{stable[20:40]}",
        "action_id": f"act_{stable[40:60]}",
        "delegator": {
            "agent_id": parent.candidate_id,
            "tenant_id": "tenant-demo",
            "certificate": parent.model_dump(mode="json"),
            "observed_artifact": parent.artifact.model_dump(mode="json"),
            "claimed_artifact_digest": parent.artifact.digest,
            "allowed_tools": ["lookup_order", "draft_recommendation"],
            "data_labels": ["tenant:tenant-demo", "classification:synthetic"],
        },
        "delegate": {
            "agent_id": child.candidate_id,
            "tenant_id": "tenant-demo",
            "certificate": child.model_dump(mode="json"),
            "observed_artifact": child.artifact.model_dump(mode="json"),
            "claimed_artifact_digest": child.artifact.digest,
            "allowed_tools": ["lookup_order", "issue_refund"],
            "data_labels": ["tenant:tenant-demo", "classification:synthetic"],
        },
        "delegated_tools": ["issue_refund"],
        "delegated_authority": "LOW_VALUE_ACTION",
        "delegated_risk_budget": 10.0,
        "parent_remaining_risk_budget": 20.0,
        "data_labels": ["tenant:tenant-demo", "classification:synthetic"],
        "delegation_depth": 1,
        "maximum_depth": 3,
        "delegation_path": [parent.candidate_id],
        "expires_at": expiration.isoformat(),
        "responsibility_owner": parent.candidate_id,
        "shared_memory_tenants": ["tenant-demo"],
        "evidence_available": True,
        "attempted_tool": "issue_refund",
        "order_id": "ORD-DELEGATION-001",
        "amount": 25.0,
        "amount_paid": 100.0,
    }


def run_demo() -> dict[str, Any]:
    started = time.perf_counter()
    payload = delegation_payload()
    first = request_json("POST", "/v1/delegations/evaluate", payload)
    duplicate = request_json("POST", "/v1/delegations/evaluate", payload)
    require(first["decision"]["allow"] is False, "delegation was unexpectedly allowed")
    require(
        "authority_laundering" in first["decision"]["detections"],
        "authority laundering was not detected",
    )
    require(first["decision"]["opa_allowed"] is False, "OPA did not deny delegation")
    require(first["gate"]["status_code"] == 403, "GATE did not refuse the capability")
    require(
        first["gate"]["capability_issued"] is False,
        "GATE issued a capability for denied delegation",
    )
    require(first["external_effect_occurred"] is False, "an external effect occurred")
    require(
        first["external_effect_count_before"] == first["external_effect_count"],
        "effect receipt count changed",
    )
    require(duplicate["duplicate_submission"] is True, "retry was not idempotent")
    output = {
        "status": "PASS",
        "phase": "6",
        "execution_mode": "deterministic_simulation",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "request": payload,
        "result": first,
        "duplicate": duplicate,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DEMO_STATE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))
    return output


def verify() -> dict[str, Any]:
    require(DEMO_STATE.exists(), "Phase 6 demo state is missing")
    state = json.loads(DEMO_STATE.read_text(encoding="utf-8"))
    result = state["result"]
    decision = result["decision"]
    delegation_id = state["request"]["delegation_id"]

    unknown_payload = json.loads(json.dumps(state["request"]))
    unknown_payload.pop("created_at", None)
    unknown_payload.pop("digest", None)
    unknown_payload["delegation_id"] = f"{delegation_id}-unknown"
    unknown_payload["mission_id"] = f"{state['request']['mission_id']}-unknown"
    unknown_payload["action_id"] = f"{state['request']['action_id']}-unknown"
    unknown_payload["evidence_available"] = False
    unknown_payload["attempted_tool"] = None
    unknown = request_json("POST", "/v1/delegations/evaluate", unknown_payload)
    require(
        unknown["decision"]["evidence_state"] == "UNKNOWN",
        "missing evidence did not produce UNKNOWN",
    )
    require(unknown["decision"]["allow"] is False, "UNKNOWN delegation was allowed")

    store = ObjectStore()
    with Session(store.engine) as session:
        event = session.get(DelegationEventRecord, delegation_id)
        require(event is not None, "delegation event is absent from PostgreSQL")
        event_count = int(
            session.scalar(
                select(func.count())
                .select_from(DelegationEventRecord)
                .where(DelegationEventRecord.delegation_id == delegation_id)
            )
            or 0
        )
        evidence = list(
            session.scalars(
                select(DelegationEvidenceRecord)
                .where(DelegationEvidenceRecord.delegation_id == delegation_id)
                .order_by(DelegationEvidenceRecord.evidence_type)
            )
        )
        effect_receipts = int(
            session.execute(
                text(
                    "SELECT count(*) FROM orbital_objects "
                    "WHERE kind='tool_receipt' "
                    "AND payload->'correlation'->>'mission_id'=:mission_id"
                ),
                {"mission_id": state["request"]["mission_id"]},
            ).scalar_one()
        )
        event_payload = event.response_payload
        object_path = event.object_path
        object_checksum = event.checksum
    require(event_count == 1, "duplicate delegation event was persisted")
    require(len(evidence) == 4, "delegation evidence records are incomplete")
    require(effect_receipts == 0, "the delegated attempt created an effect receipt")
    require(event_payload["decision"]["opa_allowed"] is False, "OPA denial was not persisted")
    require(
        event_payload["gate"]["capability_issued"] is False,
        "GATE refusal was not persisted",
    )

    minio = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
    stat = minio.stat_object(bucket, object_path)
    require(
        f"sha256:{stat.metadata['x-amz-meta-sha256']}" == object_checksum,
        "MinIO delegation checksum metadata does not match PostgreSQL",
    )

    trace_names = wait_for_trace(result["trace_id"])
    required_spans = {"agent.delegate", "policy.authorize", "capability.issue"}
    require(required_spans <= trace_names, "SigNoz delegation chain is incomplete")
    attribute_rows = query_clickhouse(
        "SELECT "
        "attributes_string['orbital.delegation.delegator.id'] AS delegator_id, "
        "attributes_string['orbital.delegation.delegate.id'] AS delegate_id, "
        "attributes_string['orbital.delegation.parent_certificate.id'] "
        "AS parent_certificate_id, "
        "attributes_string['orbital.delegation.child_certificate.id'] "
        "AS child_certificate_id, "
        "attributes_string['orbital.delegation.tools'] AS delegated_tools, "
        "attributes_string['orbital.authority.level'] AS authority_level, "
        "attributes_number['orbital.delegation.risk_budget'] AS risk_budget, "
        "attributes_string['orbital.delegation.data_labels'] AS data_labels, "
        "attributes_number['orbital.delegation.depth'] AS depth, "
        "attributes_string['orbital.delegation.expires_at'] AS expires_at "
        "FROM signoz_traces.distributed_signoz_index_v3 "
        f"WHERE trace_id='{result['trace_id']}' AND name='agent.delegate' LIMIT 1"
    )
    require(len(attribute_rows) == 1, "delegation span attributes are absent")
    span_attributes = attribute_rows[0]
    require(
        span_attributes["delegator_id"]
        == state["request"]["delegator"]["agent_id"],
        "delegator identity is absent from the delegation span",
    )
    require(
        span_attributes["delegate_id"] == state["request"]["delegate"]["agent_id"],
        "delegate identity is absent from the delegation span",
    )
    require(
        span_attributes["parent_certificate_id"]
        == state["request"]["delegator"]["certificate"]["certificate_id"],
        "parent certificate is absent from the delegation span",
    )
    require(
        span_attributes["child_certificate_id"]
        == state["request"]["delegate"]["certificate"]["certificate_id"],
        "child certificate is absent from the delegation span",
    )
    require(
        span_attributes["delegated_tools"] == "issue_refund"
        and span_attributes["authority_level"] == "LOW_VALUE_ACTION"
        and float(span_attributes["risk_budget"]) == 10.0
        and int(span_attributes["depth"]) == 1
        and bool(span_attributes["data_labels"])
        and bool(span_attributes["expires_at"]),
        "delegation scope attributes are incomplete",
    )
    log_rows = query_clickhouse(
        "SELECT count() AS count FROM signoz_logs.distributed_logs_v2 "
        "WHERE resources_string['service.name']='orbital-agent-runtime' "
        "AND body LIKE '%delegation_evaluated%' "
        f"AND body LIKE '%{delegation_id}%'"
    )
    log_count = int(log_rows[0]["count"]) if log_rows else 0
    require(log_count >= 1, "SigNoz delegation structured log is absent")
    metric_rows = query_clickhouse(
        "SELECT countDistinct(metric_name) AS count "
        "FROM signoz_metrics.distributed_metadata "
        "WHERE metric_name LIKE 'orbital.delegation.%'"
    )
    metric_count = int(metric_rows[0]["count"]) if metric_rows else 0
    require(metric_count >= 3, "SigNoz delegation metric metadata is incomplete")

    report = {
        "status": "PASS",
        "phase": "6",
        "execution_mode": "deterministic_simulation",
        "delegation_id": delegation_id,
        "mission_id": state["request"]["mission_id"],
        "trace_id": result["trace_id"],
        "evidence_state": decision["evidence_state"],
        "detections": decision["detections"],
        "opa_allowed": decision["opa_allowed"],
        "gate_status_code": result["gate"]["status_code"],
        "capability_issued": result["gate"]["capability_issued"],
        "external_effect_occurred": result["external_effect_occurred"],
        "retry_idempotent": state["duplicate"]["duplicate_submission"],
        "unknown_on_missing_evidence": True,
        "postgres_delegation_events": event_count,
        "postgres_evidence_records": len(evidence),
        "effect_receipts_for_mission": effect_receipts,
        "minio_object_path": object_path,
        "minio_checksum": object_checksum,
        "signoz_span_names": sorted(trace_names),
        "signoz_span_attributes_verified": True,
        "signoz_log_events": log_count,
        "signoz_metric_series": metric_count,
    }
    VALIDATION_STATE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("demo", "verify"))
    args = parser.parse_args()
    if args.command == "demo":
        run_demo()
    else:
        verify()


if __name__ == "__main__":
    main()
