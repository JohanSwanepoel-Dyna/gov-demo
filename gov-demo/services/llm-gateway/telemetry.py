"""OpenTelemetry tracing setup. Exports OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set."""
import os

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
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
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
