# llm-gateway

A MOCK LLM provider behind a gateway, for demonstration. No real model is called: responses are canned and chosen by intent keyword. Provider and model names are plausible labels, and its server span carries `demo.mock=true`.

Telemetry: the gateway emits its HTTP server span and guardrail spans. The caller (claims-api) emits the GenAI `chat` span and the GenAI metrics, using the usage and Azure-style content filter results returned in the response. This avoids counting tokens twice.

| Variable | Default | Purpose |
|---|---|---|
| `ACCESS_LOG` | off | Set to `on` to log every HTTP request (health probes included). Off keeps log volume low |
| `PORT` | 8100 | Listen port |
| `CONTROL_TOKEN` | none | Shared secret for the toggle API, sent as header `X-Demo-Control`. The API is disabled when unset |
| `GENAI_MODEL` | gpt-4o-mini | Default request model |
| `GENAI_RESPONSE_MODEL` | gpt-4o-mini-2024-07-18 | Value of `gen_ai.response.model` |
| `LATENCY_MIN_MS` | 300 | Minimum simulated latency |
| `LATENCY_MAX_MS` | 900 | Maximum simulated latency |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP/HTTP endpoint. Tracing export is off when unset |

## Toggle API

`GET /control/toggles` and `PUT /control/toggles` with header `X-Demo-Control`. State is in memory and resets on restart. | Toggle | Values | Effect |
|---|---|---|
| `latency` | normal, slow | normal: 300 to 900 ms. slow: 6 to 12 s |
| `provider_errors` | none, 429, 503 | Returns that status for a share of requests |
| `provider_error_rate` | 0 to 100 | Percentage of requests that fail when errors are on (default 30) |
| `guardrails` | on, off | off: no guardrail checks or filter annotations, and an injection prompt fails open and returns another citizen's (synthetic) claim summary |
| `response_mode` | grounded, hallucinated, verbose | hallucinated: wrong amount and a non-existent policy clause. verbose: long answer, high token counts |
