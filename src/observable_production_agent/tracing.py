from __future__ import annotations

import os


def configure_tracing() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "observable-production-agent"}))
    api_key = os.environ.get("PHOENIX_API_KEY")
    headers = {"authorization": "Bearer " + api_key} if api_key else None
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers)))
    trace.set_tracer_provider(provider)
