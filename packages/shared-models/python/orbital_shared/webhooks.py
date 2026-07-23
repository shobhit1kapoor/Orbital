from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qs, urlparse


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), canonical_payload(payload), hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], secret: str, signature: str) -> bool:
    return hmac.compare_digest(sign_payload(payload, secret), signature)


def _rule_id(alert: dict[str, Any], labels: dict[str, Any]) -> str | None:
    for key in ("ruleId", "rule_id", "ruleid"):
        if labels.get(key):
            return str(labels[key])
    generator_url = str(alert.get("generatorURL") or "")
    values = parse_qs(urlparse(generator_url).query).get("ruleId")
    return values[0] if values else None


def normalize_signoz_payload(
    payload: dict[str, Any],
    signoz_public_url: str,
) -> list[dict[str, Any]]:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        alerts = [payload]
    common_labels = payload.get("commonLabels")
    if not isinstance(common_labels, dict):
        common_labels = {}
    common_annotations = payload.get("commonAnnotations")
    if not isinstance(common_annotations, dict):
        common_annotations = {}

    normalized: list[dict[str, Any]] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        labels = common_labels | (
            alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
        )
        annotations = common_annotations | (
            alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}
        )
        alertname = str(
            labels.get("alertname")
            or payload.get("alertname")
            or alert.get("alertname")
            or "SigNoz safety alert"
        )
        rule_id = _rule_id(alert, labels)
        trace_id = labels.get("trace_id") or labels.get("traceId")
        item: dict[str, Any] = {
            "source": "signoz",
            "status": str(alert.get("status") or payload.get("status") or "firing"),
            "alertname": alertname,
            "certificate_id": labels.get("orbital.certificate.id"),
            "candidate_id": labels.get("orbital.candidate.id"),
            "baseline_candidate_id": labels.get("orbital.baseline.candidate.id"),
            "trace_id": str(trace_id) if trace_id else None,
            "rule_id": rule_id,
            "fingerprint": alert.get("fingerprint"),
            "starts_at": alert.get("startsAt"),
            "ends_at": alert.get("endsAt"),
            "labels": {
                key: value
                for key, value in labels.items()
                if key
                in {
                    "alertname",
                    "severity",
                    "threshold_name",
                    "threshold.name",
                    "trace_id",
                    "orbital.certificate.id",
                    "orbital.candidate.id",
                    "orbital.baseline.candidate.id",
                }
            },
            "annotations": {
                key: value
                for key, value in annotations.items()
                if key in {"summary", "description"}
            },
        }
        links: list[str] = []
        if trace_id:
            links.append(f"{signoz_public_url.rstrip('/')}/trace/{trace_id}")
        links.append(f"{signoz_public_url.rstrip('/')}/traces-explorer")
        if rule_id:
            links.append(
                f"{signoz_public_url.rstrip('/')}/alerts/overview?ruleId={rule_id}"
            )
        item["evidence_links"] = links
        item["delivery_id"] = hashlib.sha256(canonical_payload(item)).hexdigest()
        normalized.append(item)
    return normalized
