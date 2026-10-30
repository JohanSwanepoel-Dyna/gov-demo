import json
import logging
import sys
import time

try:
    from opentelemetry import trace
except ImportError:  # service without OpenTelemetry
    trace = None


class JsonFormatter(logging.Formatter):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, record):
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if trace is not None:
            ctx = trace.get_current_span().get_span_context()
            if ctx.is_valid:
                out["trace_id"] = format(ctx.trace_id, "032x")
                out["span_id"] = format(ctx.span_id, "016x")
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out)


def setup(service):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)
