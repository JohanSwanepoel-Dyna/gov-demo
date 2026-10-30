"""OpenTelemetry tracing and GenAI metrics. Exports OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set."""
import os

from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.propagators.textmap import default_getter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceState
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class DropOneAgentTraceState(TraceContextTextMapPropagator):
    """W3C trace context that forgets the Dynatrace OneAgent entry (the key ending in @dt) of an incoming
    tracestate. The OTel services continue the trace through traceparent, but if they pass that entry on, a
    OneAgent service further down takes its parent from it and skips the OTel span in between (the Java stub
    then appears to be called by web). Without the entry the Java span is parented to the OTel client span."""

    def extract(self, carrier, context=None, getter=default_getter):
        ctx = super().extract(carrier, context, getter)
        sc = trace.get_current_span(ctx).get_span_context()
        if sc.is_valid and sc.trace_state:
            kept = [(k, v) for k, v in sc.trace_state.items() if not k.endswith("@dt")]
            if len(kept) != len(sc.trace_state):
                kept_sc = SpanContext(sc.trace_id, sc.span_id, sc.is_remote, sc.trace_flags, TraceState(kept))
                ctx = trace.set_span_in_context(NonRecordingSpan(kept_sc), ctx)
        return ctx


def setup_tracing(service):
    propagate.set_global_textmap(DropOneAgentTraceState())
    resource = Resource.create({"service.name": service})
    tracer_provider = TracerProvider(resource=resource)
    readers = []
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        # Set OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta for Dynatrace histograms.
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10000))
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
