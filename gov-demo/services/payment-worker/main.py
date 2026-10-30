import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from opentelemetry import propagate, trace
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.trace import SpanKind, Status, StatusCode
from psycopg.rows import dict_row

from logsetup import setup
from telemetry import setup_tracing

setup("payment-worker")
setup_tracing("payment-worker")
URLLibInstrumentor().instrument()
tracer = trace.get_tracer("payment-worker")
log = logging.getLogger("payment-worker")

PORT = int(os.environ.get("PORT", "8200"))
POLL_INTERVAL_S = float(os.environ.get("POLL_INTERVAL_S", "1"))
MAX_CONCURRENCY = 8
# Toggle state, in memory. Defaults come from env. name -> allowed integer range.
RANGES = {"concurrency": range(1, MAX_CONCURRENCY + 1), "processing_delay_ms": range(0, 10001)}
STATE = {"concurrency": int(os.environ.get("WORKER_CONCURRENCY", "2")),
         "processing_delay_ms": int(os.environ.get("PROCESSING_DELAY_MS", "0"))}
CONTROL_TOKEN = os.environ.get("CONTROL_TOKEN")
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
BACKOFF_BASE_S = float(os.environ.get("BACKOFF_BASE_S", "2"))
LEGACY_URL = os.environ.get("LEGACY_URL", "http://legacy-stub:8300")
LEGACY_TIMEOUT_S = float(os.environ.get("LEGACY_TIMEOUT_S", "15"))
DATABASE_URL = os.environ["DATABASE_URL"]

DEQUEUE = """
UPDATE payment_queue SET status='processing', locked_at=now(), attempts=attempts+1
WHERE id = (SELECT id FROM payment_queue WHERE status='pending' AND available_at <= now()
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING id, claim_id, attempts, traceparent, tracestate,
          (extract(epoch from (now() - available_at)) * 1000)::int AS queue_wait_ms
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not CONTROL_TOKEN:
            self._send(503, {"detail": "control API disabled: CONTROL_TOKEN not set"})
        elif not hmac.compare_digest(self.headers.get("X-Demo-Control", ""), CONTROL_TOKEN):
            self._send(401, {"detail": "bad control token"})
        else:
            return True
        return False

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        elif self.path == "/control/toggles" and self._authorized():
            self._send(200, STATE)
        elif self.path not in ("/healthz", "/control/toggles"):
            self.send_error(404)

    def do_PUT(self):
        if self.path != "/control/toggles":
            return self.send_error(404)
        if not self._authorized():
            return
        try:
            changes = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            clean = {}
            for name, value in changes.items():
                if name not in RANGES:
                    return self._send(422, {"detail": f"unknown toggle {name}"})
                if int(value) not in RANGES[name]:
                    return self._send(422, {"detail": f"{name} must be {RANGES[name].start} to {RANGES[name].stop - 1}"})
                clean[name] = int(value)
        except (ValueError, TypeError):
            return self._send(422, {"detail": "body must be a JSON object of integers"})
        STATE.update(clean)
        log.info("toggles changed", extra={"fields": {"changes": clean}})
        self._send(200, STATE)

    def log_message(self, fmt, *args):
        pass


def post_payment(claim_id, amount_cents):
    body = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><PaymentRequest>'
            f"<ClaimId>{claim_id}</ClaimId><AmountCents>{int(amount_cents)}</AmountCents>"
            "</PaymentRequest></soap:Body></soap:Envelope>")
    req = urllib.request.Request(LEGACY_URL + "/legacy/PaymentService", data=body.encode(),
                                 headers={"Content-Type": "text/xml"}, method="POST")
    with urllib.request.urlopen(req, timeout=LEGACY_TIMEOUT_S) as resp:
        xml = resp.read().decode()
    m = re.search(r"<(?:\w+:)?PaymentReference>(.*?)</", xml)
    if not m:
        raise ValueError("legacy response missing PaymentReference")
    return m.group(1)


def _process(qid, claim_id, attempts, span, queue_wait_ms):
    try:
        if STATE["processing_delay_ms"]:
            time.sleep(STATE["processing_delay_ms"] / 1000)
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            amount = conn.execute("SELECT (eligibility_result->>'amount_cents')::int AS a FROM claims WHERE id=%s",
                                  (claim_id,)).fetchone()["a"]
        legacy_ref = post_payment(claim_id, amount)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("INSERT INTO payments (claim_id, amount_cents, legacy_ref) VALUES (%s,%s,%s)",
                         (claim_id, amount, legacy_ref))
            conn.execute("UPDATE claims SET status='paid' WHERE id=%s", (claim_id,))
            conn.execute("UPDATE payment_queue SET status='done', locked_at=NULL WHERE id=%s", (qid,))
        log.info("payment posted", extra={"fields": {
            "business_event": "claim.payment_posted", "claim_id": str(claim_id), "amount_cents": amount,
            "queue_wait_ms": queue_wait_ms, "legacy_ref": legacy_ref, "attempts": attempts}})
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
        final = attempts >= MAX_ATTEMPTS
        with psycopg.connect(DATABASE_URL) as conn:
            if final:
                conn.execute("UPDATE payment_queue SET status='failed', locked_at=NULL, last_error=%s WHERE id=%s",
                             (str(exc)[:500], qid))
                conn.execute("UPDATE claims SET status='failed' WHERE id=%s", (claim_id,))
            else:
                conn.execute("UPDATE payment_queue SET status='pending', locked_at=NULL, last_error=%s, "
                             "available_at = now() + make_interval(secs => %s) WHERE id=%s",
                             (str(exc)[:500], BACKOFF_BASE_S * 2 ** (attempts - 1), qid))
        fields = {"claim_id": str(claim_id), "attempts": attempts, "final": final, "error": str(exc)}
        if final:
            fields["business_event"] = "claim.payment_failed"
        log.error("payment failed", extra={"fields": fields})


def process_one():
    """Dequeue and process one row. Returns False when the queue is empty."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        item = conn.execute(DEQUEUE).fetchone()
    if not item:
        return False
    qid, claim_id, attempts = item["id"], item["claim_id"], item["attempts"]
    carrier = {k: item[k] for k in ("traceparent", "tracestate") if item[k]}
    with tracer.start_as_current_span(
            "payment_queue process", context=propagate.extract(carrier), kind=SpanKind.CONSUMER,
            attributes={"messaging.system": "postgresql", "messaging.destination.name": "payment_queue",
                        "messaging.operation.type": "process", "claim.id": str(claim_id), "queue.attempt": attempts}) as span:
        _process(qid, claim_id, attempts, span, item["queue_wait_ms"])
    return True


def poll_loop(index):
    while True:
        if index >= STATE["concurrency"]:  # this thread is above the current concurrency, stay idle
            time.sleep(1)
            continue
        try:
            if process_one():
                continue
        except Exception:
            log.exception("poll loop error")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    for i in range(MAX_CONCURRENCY):
        threading.Thread(target=poll_loop, args=(i,), daemon=True).start()
    log.info("payment-worker started", extra={"fields": {"port": PORT, "concurrency": STATE["concurrency"]}})
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
