import hashlib
import logging
import os
import random
import secrets
import socket
import time
from urllib.parse import urlparse
import uuid
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Response, UploadFile
from opentelemetry import propagate
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

import assess
import assistant
import eligibility
import legacy
import toggles
from home import build_home
from db import connect
from logsetup import setup
from telemetry import setup_tracing

setup("claims-api")
setup_tracing("claims-api")
log = logging.getLogger("claims-api")
app = FastAPI(title="claims-api")
FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz", exclude_spans=["send", "receive"])
URLLibInstrumentor().instrument()
PsycopgInstrumentor().instrument()

MAX_UPLOAD_BYTES = 1024 * 1024
PAYMENT_TYPES = ("carer_payment", "carer_allowance")
SESSIONS = {}  # token -> citizen id, in memory (resets on restart)


@app.get("/healthz")
async def healthz(response: Response):
    # async so the probe does not wait for a worker thread, which are all busy when the legacy tier is slow.
    # TCP reachability only. A SELECT here would create a root database span on every probe.
    db = urlparse(os.environ["DATABASE_URL"])
    try:
        socket.create_connection((db.hostname, db.port or 5432), timeout=2).close()
    except OSError:
        log.exception("healthz db check failed")
        response.status_code = 503
        return {"status": "unhealthy", "db": "down"}
    return {"status": "ok", "db": "up"}


def current_citizen(authorization: str = Header(default="")) -> int:
    citizen_id = SESSIONS.get(authorization.removeprefix("Bearer ").strip())
    if citizen_id is None:
        raise HTTPException(401, "not signed in")
    return citizen_id


def load_claim(conn, claim_id, citizen_id):
    claim = conn.execute("SELECT * FROM claims WHERE id=%s AND citizen_id=%s", (claim_id, citizen_id)).fetchone()
    if not claim:
        raise HTTPException(404, "claim not found")
    return claim


def pii_fields(citizen_id):
    """Only with the log_pii toggle on: identifiers that must never be logged in clear."""
    if toggles.STATE["log_pii"] != "on":
        return {}
    with connect() as conn:
        row = conn.execute("SELECT tfn, medicare_number, irn FROM citizens WHERE id=%s", (citizen_id,)).fetchone()
    return {"tfn": row["tfn"], "medicare_number": row["medicare_number"], "irn": row["irn"]} if row else {}


class Login(BaseModel):
    citizen_id: int
    passcode: str


@app.post("/api/login")
def login(body: Login):
    with connect() as conn:
        row = conn.execute("SELECT passcode_hash FROM citizens WHERE id=%s", (body.citizen_id,)).fetchone()
    if not row or hashlib.sha256(body.passcode.encode()).hexdigest() != row["passcode_hash"]:
        log.info("login failed", extra={"fields": {"citizen_id": body.citizen_id}})
        raise HTTPException(401, "invalid citizen id or passcode")
    token = secrets.token_hex(16)
    SESSIONS[token] = body.citizen_id
    log.info("login ok", extra={"fields": {"citizen_id": body.citizen_id, **pii_fields(body.citizen_id)}})
    return {"token": token}


@app.get("/api/home")
def home(citizen_id: int = Depends(current_citizen)):
    with connect() as conn:
        return build_home(conn, citizen_id)


class NewClaim(BaseModel):
    payment_type: Literal["carer_payment", "carer_allowance"]


@app.post("/api/claims", status_code=201)
def create_claim(body: NewClaim, citizen_id: int = Depends(current_citizen)):
    with connect() as conn:
        claim = conn.execute("INSERT INTO claims (citizen_id, payment_type) VALUES (%s,%s) RETURNING *",
                             (citizen_id, body.payment_type)).fetchone()
    log.info("claim draft created", extra={"fields": {"business_event": "claim.draft_created",
                                                  "claim_id": str(claim["id"]), "payment_type": body.payment_type}})
    return claim


class Details(BaseModel):
    income_band: Literal["low", "medium", "high"]
    caring_hours: int = Field(ge=0, le=168)


@app.post("/api/claims/{claim_id}/eligibility")
def check_eligibility(claim_id: uuid.UUID, body: Details, citizen_id: int = Depends(current_citizen)):
    with connect() as conn:
        claim = load_claim(conn, claim_id, citizen_id)
        if claim["status"] not in ("draft", "eligible", "ineligible"):
            raise HTTPException(409, f"claim is {claim['status']}")
        started = time.perf_counter()
        try:
            result = assess.assess(citizen_id, claim["payment_type"], body.income_band, body.caring_hours)
        except assess.LegacyUnavailable:
            log.exception("legacy customer lookup failed",
                          extra={"fields": {"claim_id": str(claim_id), **pii_fields(citizen_id)}})
            raise HTTPException(502, "customer record service unavailable")
        status = "ineligible" if result["decision"] == "ineligible" else "eligible"
        conn.execute("UPDATE claims SET details=%s, eligibility_result=%s, status=%s WHERE id=%s",
                     (Jsonb(body.model_dump()), Jsonb(result), status, claim_id))
    log.info("eligibility checked", extra={"fields": {
        "business_event": "claim.eligibility_checked", "claim_id": str(claim_id), "decision": result["decision"],
        "duration_ms": round((time.perf_counter() - started) * 1000), **pii_fields(citizen_id)}})
    return {"claim_id": claim_id, "status": status, **result}


@app.post("/api/claims/{claim_id}/documents", status_code=201)
def upload_document(claim_id: uuid.UUID, file: UploadFile, citizen_id: int = Depends(current_citizen)):
    fault = toggles.STATE["upload_fault"]
    if fault == "slow":
        time.sleep(random.uniform(3, 8))
    elif fault == "error" and random.random() < 0.15:
        log.error("upload failed", extra={"fields": {"claim_id": str(claim_id)}})
        raise HTTPException(500, "upload failed, please try again")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file larger than 1 MB")
    with connect() as conn:
        claim = load_claim(conn, claim_id, citizen_id)
        if claim["status"] != "eligible":
            raise HTTPException(409, f"claim is {claim['status']}")
        doc = conn.execute("INSERT INTO documents (claim_id, filename, size_bytes, content) VALUES (%s,%s,%s,%s) "
                           "RETURNING id, filename, size_bytes", (claim_id, file.filename or "upload", len(data), data)).fetchone()
    log.info("document uploaded", extra={"fields": {"business_event": "claim.document_uploaded",
                                                  "claim_id": str(claim_id), "size_bytes": len(data)}})
    return doc


@app.post("/api/claims/{claim_id}/submit", status_code=202)
def submit_claim(claim_id: uuid.UUID, citizen_id: int = Depends(current_citizen)):
    with connect() as conn:
        claim = load_claim(conn, claim_id, citizen_id)
        if claim["status"] != "eligible":
            raise HTTPException(409, f"claim is {claim['status']}")
        docs = conn.execute("SELECT count(*) AS n FROM documents WHERE claim_id=%s", (claim_id,)).fetchone()["n"]
        if docs == 0:
            raise HTTPException(400, "at least one document is required")
        reference = "DCS-" + secrets.token_hex(4).upper()
        carrier = {}
        propagate.inject(carrier)  # W3C context travels with the queue row to the worker
        conn.execute("INSERT INTO payment_queue (claim_id, traceparent, tracestate) VALUES (%s,%s,%s)",
                     (claim_id, carrier.get("traceparent"), carrier.get("tracestate")))
        conn.execute("UPDATE claims SET status='submitted', submitted_at=now(), reference=%s WHERE id=%s",
                     (reference, claim_id))
    log.info("claim submitted", extra={"fields": {"business_event": "claim.submitted", "claim_id": str(claim_id),
                                                "payment_type": claim["payment_type"], "reference": reference}})
    return {"claim_id": claim_id, "status": "submitted", "reference": reference}


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: uuid.UUID, citizen_id: int = Depends(current_citizen)):
    with connect() as conn:
        claim = load_claim(conn, claim_id, citizen_id)
        claim["documents"] = conn.execute("SELECT id, filename, size_bytes FROM documents WHERE claim_id=%s ORDER BY id",
                                          (claim_id,)).fetchall()
    return claim


@app.get("/control/toggles", dependencies=[Depends(toggles.require_control)])
async def get_toggles():
    return toggles.STATE


@app.put("/control/toggles", dependencies=[Depends(toggles.require_control)])
async def put_toggles(changes: dict):
    previous = toggles.STATE["eligibility_release"]
    state = toggles.update(changes)
    log.info("toggles changed", extra={"fields": {"changes": changes}})
    if state["eligibility_release"] != previous:
        # OpenPipeline turns this line into a deployment event in the tenant (docs/dynatrace-config.md).
        log.info("deployment", extra={"fields": {"deployment_event": True, "deployment_name": "eligibility-engine",
                                                 "release_version": state["eligibility_release"],
                                                 "previous_version": previous}})
    return state


class AssistantTurn(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=1000)


@app.post("/api/assistant")
def assistant_turn(body: AssistantTurn, citizen_id: int = Depends(current_citizen)):
    try:
        return assistant.handle(citizen_id, body.conversation_id, body.message)
    except Exception:
        log.exception("assistant turn failed", extra={"fields": {"conversation_id": body.conversation_id}})
        raise HTTPException(502, "assistant unavailable")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_config=None,
                access_log=os.environ.get("ACCESS_LOG", "off") == "on")
