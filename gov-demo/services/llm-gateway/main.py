"""Mock LLM provider behind a sovereign-proxy style gateway. No real model is called."""
import json
import logging
import math
import os
import random
import time
import uuid

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import SpanKind
from pydantic import BaseModel

import guardrails
import script
import toggles
from logsetup import setup
from telemetry import setup_tracing

setup("llm-gateway")
setup_tracing("llm-gateway")
log = logging.getLogger("llm-gateway")
app = FastAPI(title="llm-gateway")
FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz", exclude_spans=["send", "receive"])
tracer = trace.get_tracer("llm-gateway")
RESPONSE_MODEL = os.environ.get("GENAI_RESPONSE_MODEL", "gpt-4o-mini-2024-07-18")
DEFAULT_MODEL = os.environ.get("GENAI_MODEL", "gpt-4o-mini")
LATENCY_MIN_MS = int(os.environ.get("LATENCY_MIN_MS", "300"))
LATENCY_MAX_MS = int(os.environ.get("LATENCY_MAX_MS", "900"))
BLOCKED = "I am unable to help with that request."


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    tools: list[dict] | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/control/toggles", dependencies=[Depends(toggles.require_control)])
async def get_toggles():
    return toggles.STATE


@app.put("/control/toggles", dependencies=[Depends(toggles.require_control)])
async def put_toggles(changes: dict):
    log.info("toggles changed", extra={"fields": {"changes": changes}})
    return toggles.update(changes)


def estimate_tokens(text):
    """Whitespace split times a fixed factor. Good enough for a mock."""
    return math.ceil(len(text.split()) * 1.3)


def message_text(m):
    text = m.get("content") or ""
    for call in m.get("tool_calls") or []:
        text += " " + call["function"]["arguments"]
    return text


def guarded(conversation_id, name, check, *args):
    attrs = {"gen_ai.guardrail.name": name}
    if conversation_id:
        attrs["gen_ai.conversation.id"] = conversation_id
    with tracer.start_as_current_span(f"guardrail {name}", kind=SpanKind.INTERNAL, attributes=attrs) as span:
        action, reason = check(*args)
        span.set_attribute("demo.guardrail.action", action)
        span.set_attribute("demo.guardrail.reason", reason)
    return action, reason


@app.post("/v1/chat/completions")
def chat(req: ChatRequest, x_conversation_id: str | None = Header(default=None)):
    # The caller owns the GenAI chat span and metrics. The gateway adds its HTTP server span (automatic),
    # guardrail spans, and reports usage and content filter results in the response, like Azure OpenAI does.
    server_span = trace.get_current_span()
    server_span.set_attribute("demo.mock", True)
    if x_conversation_id:
        server_span.set_attribute("gen_ai.conversation.id", x_conversation_id)
    errors = toggles.STATE["provider_errors"]
    if errors != "none" and random.randint(1, 100) <= int(toggles.STATE["provider_error_rate"]):
        log.warning("provider error injected", extra={"fields": {"status": int(errors)}})
        raise HTTPException(int(errors), detail={"error": {"code": errors, "message": "Simulated provider error"}},
                            headers={"Retry-After": "2"} if errors == "429" else None)
    if toggles.STATE["latency"] == "slow":
        time.sleep(random.randint(6000, 12000) / 1000)
    else:
        time.sleep(random.randint(LATENCY_MIN_MS, LATENCY_MAX_MS) / 1000)
    user_text = next((m.get("content") or "" for m in reversed(req.messages) if m.get("role") == "user"), "")
    guardrail = {"action": "allow", "name": "none", "reason": "NONE"}

    enforce = toggles.STATE["guardrails"] == "on"
    mode = toggles.STATE["response_mode"]
    action, reason = guarded(x_conversation_id, "prompt_injection_check", guardrails.prompt_injection_check, user_text) \
        if enforce else ("allow", "GUARDRAILS_OFF")
    if action == "block":
        content, tool_calls, finish, options = BLOCKED, None, "content_filter", script.START_OPTIONS
        guardrail = {"action": "block", "name": "prompt_injection_check", "reason": reason}
    elif not enforce and guardrails.INJECTION.search(user_text):
        content, tool_calls, finish, options = script.LEAK, None, "stop", script.START_OPTIONS  # fails open: another citizen's data
    else:
        content, tool_calls, finish, options = script.respond(req.messages, mode)
        if content and enforce:
            for name, check, args in (("pii_check", guardrails.pii_check, (content,)),
                                      ("grounding_check", guardrails.grounding_check,
                                       (content, script.tool_amount_cents(req.messages)))):
                action, reason = guarded(x_conversation_id, name, check, *args)
                if action == "block":
                    content, finish, options = BLOCKED, "content_filter", script.START_OPTIONS
                    guardrail = {"action": "block", "name": name, "reason": reason}
                    break

    input_tokens = sum(estimate_tokens(message_text(m)) for m in req.messages)
    output_tokens = estimate_tokens(content or json.dumps([c["function"] for c in tool_calls or []]))
    # With guardrails off no filter annotations are returned, like an unfiltered deployment.
    prompt_filters, completion_filters = guardrails.azure_filter_results(guardrail["name"] == "prompt_injection_check") if enforce else ([], {})
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    response_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    log.info("chat completion", extra={"fields": {"conversation_id": x_conversation_id, "finish_reason": finish,
                                                  "input_tokens": input_tokens, "output_tokens": output_tokens,
                                                  "guardrail": guardrail["action"], "guardrails_enforced": enforce, "mode": mode}})
    return {"id": response_id, "object": "chat.completion", "created": int(time.time()), "model": RESPONSE_MODEL,
            "prompt_filter_results": prompt_filters,
            "choices": [{"index": 0, "message": message, "finish_reason": finish,
                         "content_filter_results": completion_filters}],
            "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens,
                      "total_tokens": input_tokens + output_tokens},
            "guardrail": guardrail, "suggested_replies": options}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8100")), log_config=None,
                access_log=os.environ.get("ACCESS_LOG", "off") == "on")
