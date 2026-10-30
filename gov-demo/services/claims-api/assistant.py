"""Assistant orchestration: calls the llm-gateway and runs the check_eligibility tool in a loop."""
import json
import logging
import os
import time
import urllib.error
import urllib.request

import toggles
from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind

from assess import assess

log = logging.getLogger("claims-api")
tracer = trace.get_tracer("claims-api.assistant")
meter = metrics.get_meter("claims-api.assistant")
token_usage = meter.create_histogram("gen_ai.client.token.usage", unit="{token}",
                                     description="Input and output tokens per operation")
op_duration = meter.create_histogram("gen_ai.client.operation.duration", unit="s",
                                     description="GenAI operation duration")

GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:8100")
GATEWAY_TIMEOUT_S = float(os.environ.get("LLM_GATEWAY_TIMEOUT_S", "30"))
PROVIDER = os.environ.get("GENAI_PROVIDER_NAME", "azure.ai.openai")
MODEL = os.environ.get("GENAI_MODEL", "gpt-4o-mini")
AGENT_NAME = "claims-assistant"
MAX_STEPS = 3
TEMPERATURE = 0.2
MAX_TOKENS = 512
SYSTEM_PROMPT = ("You are the Carer Support Portal assistant for a fictional Department of Community Services. "
                 "Answer questions about carer payments. Use the check_eligibility tool for eligibility questions.")
TOOL_DESCRIPTION = "Check a citizen's indicative eligibility and fortnightly amount for a carer payment."
TOOLS = [{"type": "function", "function": {
    "name": "check_eligibility", "description": TOOL_DESCRIPTION,
    "parameters": {"type": "object", "properties": {
        "payment_type": {"type": "string", "enum": ["carer_payment", "carer_allowance"]},
        "income_band": {"type": "string", "enum": ["low", "medium", "high"]},
        "caring_hours": {"type": "integer"}},
        "required": ["payment_type", "income_band", "caring_hours"]}}}]

CONVERSATIONS = {}  # (citizen_id, conversation_id) -> messages, in memory


def to_parts(m):
    """One chat message in the OpenTelemetry GenAI structured message format."""
    parts = []
    if m.get("content"):
        if m.get("role") == "tool":
            parts.append({"type": "tool_call_response", "id": m.get("tool_call_id"), "response": m["content"]})
        else:
            parts.append({"type": "text", "content": m["content"]})
    for c in m.get("tool_calls") or []:
        parts.append({"type": "tool_call", "id": c["id"], "name": c["function"]["name"],
                      "arguments": json.loads(c["function"]["arguments"])})
    return {"role": m["role"], "parts": parts}


def call_gateway(messages, conversation_id):
    """One chat completion. The client owns the GenAI chat span and metrics, as client instrumentation does."""
    started = time.perf_counter()
    base = {"gen_ai.operation.name": "chat", "gen_ai.provider.name": PROVIDER, "gen_ai.request.model": MODEL}
    attrs = {**base, "gen_ai.request.temperature": TEMPERATURE, "gen_ai.request.max_tokens": MAX_TOKENS,
             "gen_ai.conversation.id": conversation_id}
    with tracer.start_as_current_span(f"chat {MODEL}", kind=SpanKind.CLIENT, attributes=attrs) as span:
        body = json.dumps({"model": MODEL, "messages": messages, "tools": TOOLS,
                           "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}).encode()
        req = urllib.request.Request(GATEWAY_URL + "/v1/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Conversation-Id": conversation_id})
        try:
            with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            error_type = str(exc.code) if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
            span.set_attribute("error.type", error_type)
            op_duration.record(time.perf_counter() - started, {**base, "error.type": error_type})
            raise
        choice, usage = data["choices"][0], data["usage"]
        span.set_attributes({
            "gen_ai.response.id": data["id"], "gen_ai.response.model": data["model"],
            "gen_ai.response.finish_reasons": [choice["finish_reason"]],
            "gen_ai.usage.input_tokens": usage["prompt_tokens"], "gen_ai.usage.output_tokens": usage["completion_tokens"],
            # Azure OpenAI style content filter results, which the AI Observability guardrail tiles read.
            "gen_ai.prompt.prompt_filter_results": json.dumps(data.get("prompt_filter_results", [])),
            "gen_ai.completion.content_filter_results": json.dumps(choice.get("content_filter_results", {}))})
        if toggles.STATE["capture_content"] == "on":  # opt-in: records prompts and any PII in them
            span.set_attributes({
                "gen_ai.input.messages": json.dumps([to_parts(m) for m in messages]),
                "gen_ai.output.messages": json.dumps([{**to_parts(choice["message"]), "finish_reason": choice["finish_reason"]}])})
    done = {**base, "gen_ai.response.model": data["model"]}
    token_usage.record(usage["prompt_tokens"], {**done, "gen_ai.token.type": "input"})
    token_usage.record(usage["completion_tokens"], {**done, "gen_ai.token.type": "output"})
    op_duration.record(time.perf_counter() - started, done)
    return data


def run_tool(call, citizen_id, conversation_id):
    name = call["function"]["name"]
    with tracer.start_as_current_span(f"execute_tool {name}", kind=SpanKind.INTERNAL, attributes={
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name,
            "gen_ai.tool.description": TOOL_DESCRIPTION, "gen_ai.tool.call.id": call["id"],
            "gen_ai.conversation.id": conversation_id}):
        args = json.loads(call["function"]["arguments"])
        result = assess(citizen_id, args["payment_type"], args["income_band"], int(args["caring_hours"]))
    return {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}


def handle(citizen_id, conversation_id, user_message):
    history = CONVERSATIONS.setdefault((citizen_id, conversation_id), [])
    history.append({"role": "user", "content": user_message})
    flagged = False
    trace.get_current_span().set_attribute("gen_ai.conversation.id", conversation_id)  # the HTTP server span
    with tracer.start_as_current_span(f"invoke_agent {AGENT_NAME}", kind=SpanKind.INTERNAL, attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": AGENT_NAME,
            "gen_ai.agent.id": AGENT_NAME + "-1", "gen_ai.conversation.id": conversation_id,
            "gen_ai.provider.name": PROVIDER}):
        reply, options = "", []
        for _ in range(MAX_STEPS):
            data = call_gateway([{"role": "system", "content": SYSTEM_PROMPT}] + history, conversation_id)
            message = data["choices"][0]["message"]
            history.append(message)
            if data.get("guardrail", {}).get("action") == "block":
                flagged = True
            if not message.get("tool_calls"):
                reply = message.get("content") or ""
                options = data.get("suggested_replies") or []  # quick replies from the gateway, so users can just click
                break
            for call in message["tool_calls"]:
                history.append(run_tool(call, citizen_id, conversation_id))
    del history[:-20]  # keep conversations small
    log.info("assistant turn", extra={"fields": {"conversation_id": conversation_id, "flagged": flagged}})
    return {"conversation_id": conversation_id, "reply": reply, "flagged": flagged, "options": options}
