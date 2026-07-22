from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("orbital.telemetry")


def configure_telemetry(service_name: str) -> None:
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")
    resource = Resource.create({"service.name": service_name, "service.namespace": "orbital-sigma"})
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(trace_provider)
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"), export_interval_millis=10_000
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    if not getattr(configure_telemetry, "_httpx_instrumented", False):
        HTTPXClientInstrumentor().instrument()
        configure_telemetry._httpx_instrumented = True


@contextmanager
def traced(name: str, attributes: dict[str, Any] | None = None) -> Iterator[trace.Span]:
    tracer = trace.get_tracer("orbital-sigma")
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


def current_trace_ids() -> tuple[str, str]:
    """Return canonical W3C trace/span identifiers for the active span."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return "", ""
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def emit_event(event: str, **fields: Any) -> None:
    safe = {key: value for key, value in fields.items() if "token" not in key.lower()}
    logger.info(json.dumps({"event": event, **safe}, sort_keys=True, default=str))
