from __future__ import annotations

import argparse

# Raw ClickHouse queries remain single strings so generated SigNoz assets are reproducible.
# ruff: noqa: E501
import asyncio
import json
import os
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

NOTIFICATION_CHANNEL = "orbital-watchtower-local"

DASHBOARD_SQL = {
    "frontier": "SELECT toStartOfMinute(timestamp) AS timestamp, attributes_string['orbital.authority.level'] AS authority_level, avg(attributes_number['orbital.authority.verified_completion']) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'authority.evaluate' GROUP BY timestamp, authority_level ORDER BY timestamp",
    "efficiency": "SELECT toStartOfMinute(timestamp) AS timestamp, attributes_string['orbital.authority.level'] AS authority_level, avg(attributes_number['orbital.authority.efficiency']) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'authority.evaluate' GROUP BY timestamp, authority_level ORDER BY timestamp",
    "escapes": "SELECT countIf(attributes_bool['orbital.unsafe_effect'] = true) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR",
    "contributions": "SELECT attributes_string['orbital.causal.factor'] AS factor, avg(attributes_number['orbital.causal.contribution']) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'causal.contribution' GROUP BY factor ORDER BY value DESC",
    "fragility": "SELECT max(attributes_number['orbital.causal.fragility']) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'causal.analyze'",
    "branches": "SELECT timestamp, trace_id, attributes_string['orbital.causal.factor'] AS factor, attributes_number['orbital.causal.contribution'] AS contribution FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'causal.contribution' ORDER BY timestamp DESC LIMIT 100",
    "traffic": "SELECT toStartOfMinute(timestamp) AS timestamp, avg(attributes_number['orbital.rollout.traffic_percentage']) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'rollout.change' GROUP BY timestamp ORDER BY timestamp",
    "drift": "SELECT toStartOfMinute(timestamp) AS timestamp, count() AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND attributes_string['orbital.artifact.status'] = 'drifted' GROUP BY timestamp ORDER BY timestamp",
    "rollback": "SELECT timestamp, trace_id, name, attributes_string['orbital.certificate.id'] AS certificate_id, attributes_string['orbital.rollback.reason'] AS reason FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name IN ('certificate.suspend', 'rollout.change') ORDER BY timestamp DESC LIMIT 100",
    "states": "SELECT attributes_string['orbital.evidence.state'] AS evidence_state, count() AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'evidence.reconcile' GROUP BY evidence_state",
    "missing-auth": "SELECT count() AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'action.commit' AND trace_id NOT IN (SELECT trace_id FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'policy.authorize' AND attributes_string['policy.decision'] = 'allow')",
    "mismatches": "SELECT timestamp, trace_id, attributes_string['orbital.action.type'] AS semantic_action, attributes_string['orbital.observed.action'] AS observed_action FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND attributes_string['orbital.evidence.state'] = 'CONTRADICTED' ORDER BY timestamp DESC LIMIT 100",
    "verdicts": "SELECT attributes_string['orbital.certificate.verdict'] AS verdict, count() AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'certificate.issue' GROUP BY verdict",
    "task-success": "SELECT countIf(status_code = 0) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'agent.mission'",
    "latency": "SELECT toStartOfMinute(timestamp) AS timestamp, quantile(0.95)(duration_nano / 1000000) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'agent.mission' GROUP BY timestamp ORDER BY timestamp",
    "cost": "SELECT toStartOfMinute(timestamp) AS timestamp, avg(attributes_number['orbital.cost.usd']) AS value FROM signoz_traces.distributed_signoz_index_v3 WHERE timestamp > now() - INTERVAL 24 HOUR AND name = 'agent.mission' GROUP BY timestamp ORDER BY timestamp",
}


def dashboard_payload(definition: dict) -> dict:
    payload = dict(definition)
    variables = payload.get("variables", {})
    for variable in variables.values():
        if variable.get("type") == "text":
            variable["type"] = "TEXTBOX"
    widgets = []
    for widget in payload["widgets"]:
        normalized = {key: value for key, value in widget.items() if key != "query"}
        normalized.update(
            {
                "query": {
                    "queryType": "clickhouse_sql",
                    "promql": [],
                    "clickhouse_sql": [
                        {
                            "query": DASHBOARD_SQL[widget["id"]],
                            "name": "A",
                            "disabled": False,
                        }
                    ],
                    "builder": {"queryData": [], "queryFormulas": []},
                },
                "selectedLogFields": [],
                "selectedTracesFields": [],
                "thresholds": [],
                "contextLinks": {"linksData": []},
            }
        )
        widgets.append(normalized)
    payload["widgets"] = widgets
    return payload


def alert_payload(alert: dict) -> dict:
    severity = alert.get("severity", "warning")
    original_filter = alert.get("filter", "")
    if "trace_matching" in alert:
        original_filter = "name = 'action.commit'"
    signal = alert.get("signal", "traces")
    group_by = [
        (
            {"name": "trace_id", "fieldContext": "tag", "fieldDataType": "string"}
            if signal == "metrics"
            else {"name": "trace_id"}
        ),
        {
            "name": "orbital.certificate.id",
            "fieldContext": "tag",
            "fieldDataType": "string",
        },
        {
            "name": "orbital.candidate.id",
            "fieldContext": "tag",
            "fieldDataType": "string",
        },
        {
            "name": "orbital.baseline.candidate.id",
            "fieldContext": "tag",
            "fieldDataType": "string",
        },
    ]
    if signal == "metrics":
        aggregation = {
            "metricName": alert["metric"],
            "timeAggregation": "latest",
            "spaceAggregation": "min"
            if alert.get("operator") == "below"
            else "max",
        }
    else:
        aggregation = {"expression": "count()"}
    return {
        "alert": alert["name"],
        "alertType": "METRIC_BASED_ALERT" if signal == "metrics" else "TRACES_BASED_ALERT",
        "ruleType": "threshold_rule",
        "description": f"ORBITAL defensive local alert ({alert.get('signal', 'traces')}).",
        "annotations": {
            "summary": alert["name"],
            "description": (
                "Observed {{$value}} matching local ORBITAL signals; "
                "trace {{$labels.trace_id}}."
            ),
        },
        "labels": {"system": "orbital-sigma", "severity": severity},
        "evaluation": {
            "kind": "rolling",
            "spec": {"frequency": "1m", "evalWindow": "1m"},
        },
        "notificationSettings": {
            "usePolicy": False,
            "renotify": {"enabled": False},
        },
        "condition": {
            "compositeQuery": {
                "queryType": "builder",
                "panelType": "graph",
                "queries": [
                    {
                        "type": "builder_query",
                        "spec": {
                            "name": "A",
                            "signal": signal,
                            "disabled": False,
                            "aggregations": [aggregation],
                            "filter": {"expression": original_filter},
                            "groupBy": group_by,
                            "order": [
                                {
                                    "key": {
                                        "name": "__result"
                                        if signal == "metrics"
                                        else "count()"
                                    },
                                    "direction": "desc",
                                }
                            ],
                            "limit": 100,
                            **({"stepInterval": 60} if signal == "metrics" else {}),
                        },
                    }
                ],
            },
            "selectedQueryName": "A",
            "thresholds": {
                "kind": "basic",
                "spec": [
                    {
                        "name": "critical" if severity == "critical" else "warning",
                        "target": alert.get("threshold", 0),
                        "op": alert.get("operator", "above"),
                        "matchType": "at_least_once",
                        "channels": [NOTIFICATION_CHANNEL],
                    }
                ],
            },
        },
    }


def result_error(result: object) -> str | None:
    content = str(getattr(result, "content", result))
    lowered = content.lower()
    if getattr(result, "isError", False) or "validation error" in lowered or "error:" in lowered:
        return content
    return None


def result_json(result: object) -> dict:
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    return {}


async def main(inspect_tools: bool = False) -> None:
    url = os.getenv("SIGNOZ_MCP_URL", "http://localhost:18000/mcp")
    output = {"dashboards": [], "alerts": [], "errors": []}
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            available = {tool.name for tool in tools}
            if inspect_tools:
                selected = {}
                for tool in tools:
                    if tool.name not in {
                        "signoz_create_dashboard",
                        "signoz_create_alert",
                        "signoz_create_notification_channel",
                        "signoz_list_alerts",
                        "signoz_list_alert_rules",
                        "signoz_get_alert",
                        "signoz_get_alert_history",
                        "signoz_update_alert",
                        "signoz_list_dashboards",
                    }:
                        continue
                    schema = tool.inputSchema
                    details: dict[str, object] = {"required": schema.get("required", [])}
                    if tool.name in {
                        "signoz_create_notification_channel",
                        "signoz_list_alerts",
                        "signoz_list_alert_rules",
                        "signoz_get_alert",
                        "signoz_get_alert_history",
                        "signoz_update_alert",
                        "signoz_list_dashboards",
                    }:
                        details["properties"] = schema.get("properties", {})
                    elif tool.name == "signoz_create_alert":
                        condition = schema["properties"]["condition"]
                        composite = condition["properties"]["compositeQuery"]
                        details.update(
                            {
                                "condition_required": condition.get("required", []),
                                "composite_required": composite.get("required", []),
                                "top_properties": sorted(schema.get("properties", {})),
                            }
                        )
                    else:
                        widget = schema["properties"]["widgets"]["items"]
                        query = widget["properties"]["query"]
                        details.update(
                            {
                                "widget_required": widget.get("required", []),
                                "query_required": query.get("required", []),
                                "context_links": widget["properties"]["contextLinks"],
                                "top_properties": sorted(schema.get("properties", {})),
                            }
                        )
                    selected[tool.name] = details
                selected["matching_tool_names"] = [
                    tool.name
                    for tool in tools
                    if "alert" in tool.name or "dashboard" in tool.name
                ]
                print(json.dumps(selected, indent=2))
                return
            if "signoz_create_dashboard" not in available:
                raise RuntimeError("SigNoz MCP dashboard tools are unavailable")
            if {
                "signoz_list_notification_channels",
                "signoz_create_notification_channel",
            } <= available:
                channels = await session.call_tool("signoz_list_notification_channels", {})
                if NOTIFICATION_CHANNEL not in str(channels.content):
                    channel = await session.call_tool(
                        "signoz_create_notification_channel",
                        {
                            "type": "webhook",
                            "name": NOTIFICATION_CHANNEL,
                            "webhook_url": "http://watchtower-relay:8000/v1/relay/signoz",
                            "webhook_username": "orbital-signoz",
                            "webhook_password": os.getenv(
                                "ORBITAL_WEBHOOK_SECRET", "development-only"
                            ),
                            "send_resolved": True,
                        },
                    )
                    error = result_error(channel)
                    if error:
                        output["errors"].append({"name": NOTIFICATION_CHANNEL, "error": error})
            dashboard_listing = ""
            if "signoz_list_dashboards" in available:
                dashboard_listing = str(
                    (await session.call_tool("signoz_list_dashboards", {})).content
                )
            for path in sorted(Path("dashboards").glob("*.json")):
                definition = json.loads(path.read_text(encoding="utf-8"))
                if definition["title"] in dashboard_listing:
                    output["dashboards"].append(
                        {"path": str(path), "result": "already provisioned"}
                    )
                    continue
                try:
                    result = await session.call_tool(
                        "signoz_create_dashboard", dashboard_payload(definition)
                    )
                    error = result_error(result)
                    if error:
                        output["errors"].append({"path": str(path), "error": error})
                    else:
                        output["dashboards"].append(
                            {"path": str(path), "result": str(result.content)}
                        )
                except Exception as exc:
                    output["errors"].append({"path": str(path), "error": str(exc)})
            alert_manifest = yaml.safe_load(Path("alerts/alerts.yaml").read_text(encoding="utf-8"))
            alert_rules: dict[str, dict] = {}
            if "signoz_list_alert_rules" in available:
                listing = await session.call_tool(
                    "signoz_list_alert_rules", {"limit": 1000, "offset": 0}
                )
                alert_rules = {
                    item["alert"]: item
                    for item in result_json(listing).get("data", [])
                    if item.get("alert")
                }
            for alert in alert_manifest["alerts"]:
                try:
                    payload = alert_payload(alert)
                    existing = alert_rules.get(alert["name"])
                    if existing and "signoz_update_alert" in available:
                        result = await session.call_tool(
                            "signoz_update_alert",
                            payload | {"id": existing["ruleId"]},
                        )
                        action = "updated"
                    elif existing:
                        output["alerts"].append(
                            {"name": alert["name"], "result": "already provisioned"}
                        )
                        continue
                    else:
                        result = await session.call_tool("signoz_create_alert", payload)
                        action = "created"
                    error = result_error(result)
                    if error:
                        output["errors"].append({"name": alert["name"], "error": error})
                    else:
                        output["alerts"].append(
                            {
                                "name": alert["name"],
                                "action": action,
                                "result": str(result.content),
                            }
                        )
                except Exception as exc:
                    output["errors"].append({"name": alert["name"], "error": str(exc)})
    Path("data/demo-output").mkdir(parents=True, exist_ok=True)
    Path("data/demo-output/signoz-provisioning.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    if output["errors"]:
        raise SystemExit(
            "SigNoz provisioning completed with "
            f"{len(output['errors'])} errors; inspect "
            "data/demo-output/signoz-provisioning.json"
        )
    print(
        json.dumps(
            {"dashboards": len(output["dashboards"]), "alerts": len(output["alerts"])}, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect-tools", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.inspect_tools))
