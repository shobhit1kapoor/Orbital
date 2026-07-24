from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from opentelemetry import metrics, trace
from orbital_semconv import ATTRIBUTES, configure_telemetry, current_trace_ids, traced
from orbital_shared.webhooks import sign_payload
from run_hero_demo import BASE, artifact

MCP_URL = os.getenv("SIGNOZ_MCP_URL", "http://orbital-mcp:8000/mcp")
CLICKHOUSE_URL = os.getenv(
    "SIGNOZ_CLICKHOUSE_URL", "http://orbital-telemetrystore-clickhouse-0-0:8123"
)
WEBHOOK_SECRET = os.getenv("ORBITAL_WEBHOOK_SECRET", "development-only")
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Live alert verification failed: {message}")


def post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def issue_certificate(candidate_id: str, digest: str) -> dict[str, Any]:
    response = post(
        f"{BASE['certifier']}/v1/certificates/issue",
        {
            "candidate_id": candidate_id,
            "artifact": artifact(digest),
            "total_runs": 1000,
            "task_successes": 981,
            "grounded_successes": 981,
            "unsafe_attempts": 64,
            "escaped_unsafe_effects": 0,
            "evidence_parity": 1.0,
            "policy_completeness": 1.0,
            "mission_coverage": 0.91,
            "replay_fidelity": 0.94,
            "sensor_health": 1.0,
            "maximum_safe_refund_usd": 25,
        },
    )
    return response["certificate"]


def result_json(result: object) -> dict[str, Any]:
    for item in getattr(result, "content", []):
        value = getattr(item, "text", None)
        if value:
            return json.loads(value)
    return {}


def emit_critical_signals(
    certificate_id: str,
    candidate_id: str,
    baseline_candidate_id: str,
) -> dict[str, str]:
    configure_telemetry("orbital-phase2-alert-fixtures")
    common: dict[str, Any] = {
        ATTRIBUTES["certificate_id"]: certificate_id,
        ATTRIBUTES["candidate_id"]: candidate_id,
        ATTRIBUTES["execution_mode"]: "controlled_fault_injection",
        ATTRIBUTES["risk_class"]: "critical",
        "orbital.baseline.candidate.id": baseline_candidate_id,
        "orbital.phase": "phase2-live-alerts",
    }
    spans = {
        "ORBITAL Uncertified Agent Execution": (
            "agent.mission",
            {
                key: value
                for key, value in common.items()
                if key != ATTRIBUTES["certificate_id"]
            },
        ),
        "ORBITAL Artifact Drift": (
            "phase2.artifact.drift",
            common | {ATTRIBUTES["artifact_status"]: "drifted"},
        ),
        "ORBITAL Missing Authorization": (
            "action.commit",
            common | {"orbital.action.authorization_present": False},
        ),
        "ORBITAL Evidence Mismatch": (
            "evidence.reconcile",
            common | {ATTRIBUTES["evidence_state"]: "CONTRADICTED"},
        ),
        "ORBITAL Unsafe External Effect": (
            "effect.verify",
            common | {"orbital.unsafe_effect": True},
        ),
        "ORBITAL Policy Bundle Mismatch": (
            "policy.bundle.verify",
            common | {"orbital.policy.status": "mismatch"},
        ),
    }
    trace_ids: dict[str, str] = {}
    for alertname, (span_name, attributes) in spans.items():
        with traced(span_name, attributes):
            trace_ids[alertname], _ = current_trace_ids()

    meter = metrics.get_meter("orbital-phase2-alert-fixtures")
    metric_values = {
        "ORBITAL Canary Regression": ("orbital.canary.quality_delta", -1.0),
        "ORBITAL OBI Sensor Loss": ("orbital.sensor.obi.healthy", 0.0),
    }
    for alertname, (metric_name, value) in metric_values.items():
        with traced(
            "phase2.metric.fixture",
            common | {"orbital.metric.name": metric_name, "orbital.metric.value": value},
        ):
            trace_id, _ = current_trace_ids()
            trace_ids[alertname] = trace_id
            gauge = meter.create_gauge(metric_name)
            gauge.set(
                value,
                common
                | {
                    "trace_id": trace_id,
                    "orbital.alert.name": alertname,
                },
            )

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=10_000)
    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "force_flush"):
        meter_provider.force_flush(timeout_millis=10_000)
    return trace_ids


def query_rollback_traces(certificate_id: str) -> list[dict[str, Any]]:
    sql = """
SELECT trace_id, name, count() AS span_count
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp > now() - INTERVAL 15 MINUTE
  AND attributes_string['orbital.certificate.id'] = {certificate_id:String}
  AND name IN ('signoz.webhook.accept', 'watchtower.rollback',
               'certificate.suspend', 'rollout.change')
GROUP BY trace_id, name
ORDER BY name, trace_id
FORMAT JSON
"""
    response = httpx.post(
        CLICKHOUSE_URL,
        params={"param_certificate_id": certificate_id},
        content=sql,
        headers={"content-type": "text/plain"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("data", [])


async def verify() -> dict[str, Any]:
    manifest = yaml.safe_load(Path("alerts/alerts.yaml").read_text(encoding="utf-8"))
    critical_names = {
        item["name"] for item in manifest["alerts"] if item.get("severity") == "critical"
    }
    require(len(critical_names) == 8, "critical alert manifest is incomplete")

    baseline = issue_certificate(
        "candidate-v2-fixed-baseline", "sha256:phase2-baseline-tool-schema"
    )
    canary = issue_certificate(
        "candidate-v3-phase2-canary", "sha256:phase2-canary-tool-schema"
    )
    post(
        f"{BASE['control']}/v1/rollouts",
        {
            "candidate_id": canary["candidate_id"],
            "certificate_id": canary["certificate_id"],
            "percentage": 10,
        },
    )

    async with streamable_http_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            rules: dict[str, dict[str, Any]] = {}
            quiet_deadline = time.monotonic() + 180
            while time.monotonic() < quiet_deadline:
                listing = result_json(
                    await session.call_tool(
                        "signoz_list_alert_rules", {"limit": 1000, "offset": 0}
                    )
                )
                rules = {
                    item["alert"]: item
                    for item in listing.get("data", [])
                    if item.get("alert") in critical_names
                }
                if set(rules) == critical_names and all(
                    item.get("state") in {"inactive", "nodata"} for item in rules.values()
                ):
                    break
                await asyncio.sleep(10)
            require(set(rules) == critical_names, "one or more critical rules are absent")
            require(
                all(
                    item.get("state") in {"inactive", "nodata"} for item in rules.values()
                ),
                "critical alert rules did not return to a quiet state",
            )

            started_ms = int(time.time() * 1000)
            trace_ids = emit_critical_signals(
                canary["certificate_id"],
                canary["candidate_id"],
                baseline["candidate_id"],
            )

            histories: dict[str, dict[str, Any]] = {}
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                for name, rule in rules.items():
                    history = result_json(
                        await session.call_tool(
                            "signoz_get_alert_history",
                            {
                                "id": rule["ruleId"],
                                "start": started_ms - 10_000,
                                "end": int(time.time() * 1000),
                                "state": "firing",
                                "limit": 100,
                                "order": "desc",
                            },
                        )
                    )
                    items = history.get("data", {}).get("items", [])
                    fresh = [
                        item
                        for item in items
                        if int(item.get("unixMilli") or 0) >= started_ms - 10_000
                    ]
                    if fresh:
                        histories[name] = {
                            "rule_id": rule["ruleId"],
                            "web_url": rule["webUrl"].replace(
                                "http://orbital-signoz-0:8080", "http://localhost:8080"
                            ),
                            "items": fresh,
                        }
                if set(histories) == critical_names:
                    break
                await asyncio.sleep(10)
            require(
                set(histories) == critical_names,
                f"missing live firing history for {sorted(critical_names - set(histories))}",
            )

    deadline = time.monotonic() + 180
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = httpx.get(f"{BASE['watchtower']}/v1/runtime/status", timeout=10)
        response.raise_for_status()
        status = response.json()
        current_deliveries = [
            item
            for item in status.get("webhooks", [])
            if item.get("certificate_id") == canary["certificate_id"]
            and item.get("status") == "firing"
            and item.get("signature_verified") is True
        ]
        if current_deliveries:
            break
        await asyncio.sleep(5)
    require(
        bool(current_deliveries),
        "SigNoz did not deliver a signed firing webhook for the active canary",
    )

    webhook = current_deliveries[0]
    duplicate = httpx.post(
        f"{BASE['watchtower']}/v1/webhooks/signoz",
        json=webhook["payload"],
        headers={
            "x-orbital-signature": sign_payload(webhook["payload"], WEBHOOK_SECRET)
        },
        timeout=30,
    )
    duplicate.raise_for_status()
    duplicate_result = duplicate.json()
    require(duplicate_result.get("duplicate_delivery") is True, "duplicate was not detected")
    require(
        duplicate_result.get("idempotent_replay") is True,
        "duplicate webhook repeated the rollback",
    )

    status = httpx.get(f"{BASE['watchtower']}/v1/runtime/status", timeout=10).json()
    suspension = next(
        (
            item
            for item in status.get("suspensions", [])
            if item.get("certificate_id") == canary["certificate_id"]
        ),
        None,
    )
    require(suspension is not None, "certificate suspension evidence is missing")
    require(suspension["status"] == "suspended", "certificate was not suspended")
    require(suspension["traffic_percentage"] == 0, "candidate traffic is not zero")
    require(
        status["rollout"]["candidate_id"] == baseline["candidate_id"],
        "last certified baseline was not restored",
    )
    require(status["rollout"]["percentage"] == 100, "baseline traffic is not 100 percent")

    deadline = time.monotonic() + 60
    rollback_traces: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        rollback_traces = query_rollback_traces(canary["certificate_id"])
        names = {item["name"] for item in rollback_traces}
        if {"certificate.suspend", "rollout.change", "signoz.webhook.accept"} <= names:
            break
        await asyncio.sleep(3)
    names = {item["name"] for item in rollback_traces}
    require("certificate.suspend" in names, "SigNoz lacks suspension trace evidence")
    require("rollout.change" in names, "SigNoz lacks rollback trace evidence")
    require("signoz.webhook.accept" in names, "SigNoz lacks webhook acceptance evidence")

    relevant_events = [
        item
        for item in status["webhooks"]
        if item.get("certificate_id") == canary["certificate_id"]
    ]
    require(
        all(len(item.get("evidence_links", [])) >= 3 for item in relevant_events),
        "Watchtower event links are incomplete",
    )

    result = {
        "status": "PASS",
        "critical_alerts": sorted(critical_names),
        "history": histories,
        "fixture_trace_ids": trace_ids,
        "webhook_deliveries": len(relevant_events),
        "duplicate_delivery": duplicate_result,
        "suspension": suspension,
        "rollout": status["rollout"],
        "rollback_traces": rollback_traces,
        "baseline_certificate_id": baseline["certificate_id"],
        "canary_certificate_id": canary["certificate_id"],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "phase2-alert-verification.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    asyncio.run(verify())
