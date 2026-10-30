# claims-api

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | required | Postgres DSN |
| `ACCESS_LOG` | off | Set to `on` to log every HTTP request (health probes included). Off keeps log volume low |
| `PORT` | 8000 | Listen port |
| `LEGACY_URL` | http://legacy-stub:8300 | Legacy stub base URL |
| `LEGACY_TIMEOUT_S` | 15 | Legacy call timeout |
| `CONTROL_TOKEN` | none | Shared secret for the toggle API, sent as header `X-Demo-Control`. The API is disabled when unset |
| `CAPTURE_CONTENT` | off | Initial value of the `capture_content` toggle. When on, `chat` spans record `gen_ai.input.messages` and `gen_ai.output.messages`, including any PII in prompts |
| `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE` | unset | Set to `delta` for Dynatrace histograms |

Eligibility rules are in `eligibility.py`. All values are fictional.
| `LLM_GATEWAY_URL` | http://llm-gateway:8100 | Assistant calls this gateway |
| `LLM_GATEWAY_TIMEOUT_S` | 30 | Gateway call timeout |
| `GENAI_PROVIDER_NAME` | azure.ai.openai | `gen_ai.provider.name` on agent spans |
| `GENAI_MODEL` | gpt-4o-mini | Model sent to the gateway |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP/HTTP endpoint. Tracing export is off when unset |

## Toggle API

`GET /control/toggles` and `PUT /control/toggles` with header `X-Demo-Control`. State is in memory and resets on restart. 
| Toggle | Values | Effect |
|---|---|---|
| `capture_content` | on, off | on: `chat` spans record prompts and outputs, including any PII |
| `eligibility_release` | v1, v2_bad | v2_bad: slower, 10% errors, wrong decisions for ages 45 to 54. Changing it logs a deployment event |
| `upload_fault` | none, slow, error | slow: 3 to 8 s. error: 15% HTTP 500 |
| `log_pii` | on, off | on: login and eligibility logs include TFN and Medicare number in clear |
 These paths are not under `/api`, so the web proxy does not expose them.
