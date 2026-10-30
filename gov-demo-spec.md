# Government Demo App: Build Specification

Target builder: Claude Code in VS Code. Target runtime: Docker Compose (dev) and k3s (lab, with existing Dynatrace Operator and DynaKube).
Status: design locked except items in section 14. Phase 0 built and accepted (see PROGRESS.md). Repo root is gov-demo/ beside this file.

---

## 1. Purpose and constraints

| Item | Requirement |
|---|---|
| Purpose | Small, government-flavoured demo that shows Dynatrace across full-stack, RUM, AI Observability, security, logs and SLOs |
| Fictional agency | "Department of Community Services" (DCS), portal name "Carer Support Portal". No real agency branding |
| Fictional policy | All eligibility rules, thresholds and payment amounts are invented. Mark them as fictional in the UI footer and README |
| Data | Synthetic only. Generated TFN-style (9 digit) and Medicare-style (10 digit + IRN) values, format-valid, not tied to real people |
| Size | 5 services, Postgres, Locust. Target 1500 lines or fewer of application code in total (excluding seed data and frontend assets) |
| Dependencies | Minimal, versions pinned. No ORM in Python (use psycopg). No frontend build step (vanilla JS, ES modules) |
| Network | Lab only. The deliberately vulnerable library in the legacy stub means the stack must not be exposed to the internet |

## 2. Instructions for Claude Code

- Follow this spec. Do not add services, frameworks or features not listed.
- Build in the phase order in section 12. Stop at the end of each phase and run its acceptance checks.
- Keep each service small. Prefer one file per concern. No abstraction layers beyond what is needed.
- Do not use emojis. Do not use em dashes in code comments, docs or UI text.
- All configuration via environment variables. Document every variable in a table in the service README.
- Every service exposes `GET /healthz`. Every service logs structured JSON to stdout.
- Every service has a Dockerfile, a pinned base image, and a non-root user.
- If a requirement is ambiguous or marked unverified, state the assumption in the phase summary. Do not invent Dynatrace behaviour.
- Create a repo-level `CLAUDE.md` containing this section and the repo layout.
- Validation and steering protocol:
  - Test each piece as it is built (run it, call it, check logs), not only at phase end. Report real command output, including failures.
  - At the end of each phase, stop and give the user a short summary: what was built, acceptance results (pass or fail with evidence), assumptions made, and open items touched. Wait for the user to steer before starting the next phase.
  - Where behaviour can only be confirmed in the Dynatrace tenant (section 14 items), ask the user to check the tenant view, or use the Dynatrace MCP server if it is configured, and record the outcome.
  - If a decision or a spec gap comes up, update this spec in the same step and note the change in the progress log.
  - Ask before any action that touches a shared cluster or tenant (apply, delete, token use). The current kubectl context may not be the lab k3s cluster, so confirm the context before any `kubectl` command.
- Progress tracking: maintain `PROGRESS.md` at the repo root. It holds a phase checklist (not started, in progress, done, blocked), the current phase, a dated log of decisions and spec changes, and the status of each section 14 item. Update it at every phase boundary and whenever a decision is made.

## 3. Architecture

| # | Service | Stack | Port | Role |
|---|---|---|---|---|
| 1 | `web` | Node 20, Express | 8080 | Serves SPA, proxies `/api/*` to `claims-api`, injects RUM snippet |
| 2 | `claims-api` | Python 3.12, FastAPI | 8000 | Identity module, claims, eligibility module, documents, assistant orchestration, toggle API |
| 3 | `llm-gateway` | Python 3.12, FastAPI | 8100 | Mock LLM provider behind a sovereign-proxy style gateway, scripted conversations, guardrails, toggle API |
| 4 | `payment-worker` | Python 3.12 | 8200 (health and control only) | Polls Postgres queue, posts payments to legacy stub |
| 5 | `legacy-stub` | Java 21, Spring Boot 3 (web starter only) | 8300 | SOAP-style XML over HTTP, bounded thread pool, latency toggle, old library |
| - | `postgres` | Postgres 16 | 5432 | Data and queue |
| - | `locust` | Python, Locust | 8089 | Protocol load generator, always on |
| - | Playwright | Node | n/a | Browser load, on demand, not in standing stack |

### Call graph

| From | To | Protocol | Purpose |
|---|---|---|---|
| Browser | `web` | HTTP | SPA, API calls |
| `web` | `claims-api` | HTTP/JSON | All `/api/*` |
| `claims-api` | `legacy-stub` | HTTP/XML | Customer record lookup during eligibility |
| `claims-api` | `postgres` | SQL | Claims, documents, queue insert |
| `claims-api` | `llm-gateway` | HTTP/JSON (OpenAI-style chat shape) | Assistant turns |
| `payment-worker` | `postgres` | SQL | Dequeue with `FOR UPDATE SKIP LOCKED` |
| `payment-worker` | `legacy-stub` | HTTP/XML | Payment posting |

## 4. Repo layout

```
gov-demo/
  CLAUDE.md
  PROGRESS.md             # phase checklist, decision log, open item status
  README.md
  Makefile
  docker-compose.yml
  .env.example
  db/
    schema.sql
    seed.py
  services/
    web/
    claims-api/
    llm-gateway/
    payment-worker/
    legacy-stub/
  load/
    locust/
      locustfile.py
      shapes.py
    browser/              # Playwright, on demand
  scenarios/
    scenarios.yaml
    run_scenario.py
  k8s/
    namespace.yaml
    postgres.yaml
    services.yaml         # one Deployment and Service per app service
    locust.yaml
    kustomization.yaml
  scripts/
    deploy.sh             # one command deploy to the current kubectl context (make deploy)
    secrets.sh            # make secrets-init and secrets-check
  secrets/                # gitignored values, committed *.example templates
  docs/
    runbook.md            # demo script per scenario
    deploy.md             # deploy to your cluster, local or through a registry
    dynatrace-config.md   # checklist for tenant-side configuration
    openpipeline/         # pipelines and routing for business events, deployment event and masking
    slos/                 # one SLO definition per file
    dashboards/           # dashboard generator and the generated JSON
```

## 5. Data model (Postgres)

| Table | Columns (key ones) | Notes |
|---|---|---|
| `citizens` | id, name, dob, tfn, medicare_number, irn, address, risk_flag | Seeded, 500 rows, synthetic |
| `claims` | id (uuid), citizen_id, payment_type, status, created_at, submitted_at, details (jsonb: income band, caring hours), eligibility_result, reference | Status: draft, eligible, ineligible, submitted, paid, failed |
| `documents` | id, claim_id, filename, size_bytes, content (bytea, max 1 MB), uploaded_at | Small files only |
| `payment_queue` | id, claim_id, status, attempts, available_at, locked_at, traceparent, tracestate, last_error | Status: pending, processing, done, failed. `traceparent` carries W3C context from submit to worker |
| `payments` | id, claim_id, amount_cents, legacy_ref, posted_at | Written by worker after legacy success |

Seed script generates citizens and prints a CSV of usable login credentials for Locust and Playwright.

## 6. Service contracts

### 6.1 `claims-api`

| Method and path | Purpose | Notes |
|---|---|---|
| `POST /api/login` | Identity module. Body: citizen id, passcode | Returns session token. If `step_up` condition met, returns `step_up_required` |
| `POST /api/login/step-up` | Second factor stub (fixed code) | Adds an extra span and a latency slice |
| `POST /api/claims` | Create draft | Emits business event `claim.draft_created` |
| `POST /api/claims/{id}/eligibility` | Body: income_band, caring_hours. Age comes from the citizen record, residency from the legacy lookup. Run rules and legacy lookup | Calls `legacy-stub` synchronously. Emits `claim.eligibility_checked` |
| `POST /api/claims/{id}/documents` | Multipart upload | Subject to `upload_fault` toggle. Emits `claim.document_uploaded` |
| `POST /api/claims/{id}/submit` | Insert queue row, store current `traceparent` and `tracestate` | Returns 202 with reference. Emits `claim.submitted` |
| `GET /api/claims/{id}` | Status | Polled by frontend after submit |
| `POST /api/assistant` | Assistant turn | Body: conversation_id, message. Orchestrates tool loop (6.4) |
| `GET /control/toggles`, `PUT /control/toggles` | Toggle API | Header `X-Demo-Control` shared secret |
| `GET /healthz` | Health | |

Eligibility rules (fictional, deterministic, keep in one file): age band, income band, caring hours, residency flag, plus `risk_flag` forcing manual review. Return decision (eligible, ineligible, manual_review), reason codes and an indicative fortnightly amount. `manual_review` is stored with claim status `eligible` and the claim proceeds. The amount is used to detect hallucinated assistant answers.

### 6.2 `legacy-stub`

| Endpoint | Purpose |
|---|---|
| `POST /legacy/CustomerService` | SOAP-style XML request, returns customer record |
| `POST /legacy/PaymentService` | SOAP-style XML request, returns payment reference |
| `GET/PUT /control/toggles` | Toggle API |
| `GET /healthz` | Health |

Health and the toggle API are also served on a second port (8301) with their own threads, so Kubernetes probes and scenario resets still work when the slow mode and a small pool saturate every request thread. The probes, the Compose healthcheck and the scenario runner use 8301.

Behaviour requirements:

- Tomcat max threads 8, accept count 50, so queueing is real under load. Make both configurable.
- Latency model: base delay plus jitter per operation, controlled by toggle.
- Deliberately old dependency that Dynatrace can flag. Candidate: an older Log4j 2.x release with a published critical CVE, actually loaded at runtime (a call that initialises it), because analysis is of loaded libraries. Verify detection in the tenant. If not flagged, pick another library with a published CVE.
- JVM heap capped via `-Xmx`. Default 384m, adjust after measurement.
- Web starter only. No JPA, no Security, no Spring-WS.

### 6.3 `payment-worker`

- Loop: select one `pending` row where `available_at <= now()` using `FOR UPDATE SKIP LOCKED`, mark `processing`, process, mark `done` or `failed`.
- Extract `traceparent` and `tracestate` from the row, start a consumer span as child of that context. This is manual instrumentation because table polling is not recognised as messaging.
- Call `legacy-stub` PaymentService, write `payments` row, update claim status to `paid`. Emit `claim.payment_posted` or `claim.payment_failed`.
- Retry with backoff up to 3 attempts. Configurable concurrency (default 2) and poll interval.
- Small HTTP server for `/healthz` and `/control/toggles`.

### 6.4 `llm-gateway`

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | OpenAI-style request and response, including `tool_calls` and `usage` |
| `GET/PUT /control/toggles` | Toggle API |
| `GET /healthz` | Health |

Internals: input guardrail, script matcher, response builder, output guardrail, telemetry. The script matcher is deterministic and context-aware so demos read naturally: it greets, remembers eligibility details given earlier in the conversation and asks only for what is missing, quotes the inputs it used, acknowledges (without echoing) a TFN or similar identifier in the user's message, and explains the claim process on request. Keep amounts exact so the grounding check can compare them. The gateway response also carries `suggested_replies` (label and message pairs, a non-standard field) for the next sensible choices, such as hour and income buttons while details are missing and what-if checks after a result. `claims-api` returns them as `options` from `/api/assistant`. No real model is called. The script matcher selects a canned response by intent keyword. Tool call for eligibility is returned when the intent is an eligibility question and no tool result is in the conversation yet. When a tool result is present, the gateway composes the grounded answer from it.

Assistant tool loop (owned by `claims-api`):

1. Receive user message and conversation_id.
2. Call gateway with messages and tool definitions (`check_eligibility`).
3. If response contains a tool call, execute it against the local eligibility module, append the result, call the gateway again.
4. Return the final text to the frontend with a `flagged` field if the gateway reports a guardrail action.

### 6.5 `web`

- Pages: login, step-up, payment type selection, claim details, eligibility result, document upload, review and submit, status, assistant widget (persistent bottom-right).
- Each step is a distinct URL path (`/login`, `/payment-type`, `/details`, `/eligibility`, `/upload`, `/review`, `/status`) using History API routing, and `web` serves the single page app for all of them. Hash routes were tried first and RUM recorded a single view `/` for the whole journey, so they do not work for funnels.
- RUM comes from OneAgent automatic injection into the HTML served by `web` (verified on the lab cluster). No snippet URL or variable is needed. The app runs without RUM where OneAgent is absent (Compose). Injection only happens for browser-like requests, so curl does not show it.
- The assistant works by clicking alone: after every reply the widget shows the assistant's suggested replies as buttons that change with the conversation, with a free text box as a secondary option. The three labelled demo prompts stay on screen at all times.
- Assistant widget opens with a greeting and one-click prompts for demonstrations: three normal prompts (eligibility, documents, payment timing) and three labelled demo prompts (prompt injection, a message with a synthetic TFN, a long answer) that mirror the assistant prompts used for load generation.
- Assistant widget generates a conversation id per browser session (use the RUM session id if the RUM API exposes it, else a UUID) and sends it in the request body and an `X-Conversation-Id` header.
- Client-side custom action names for each step (for example `step_upload`), to make funnel definition easy. Use `id = dtrum.enterAction(name, "custom")` then `dtrum.leaveAction(id)`. Verified on the lab tenant (new RUM experience): the call succeeds but these classic custom actions are not stored in `user.events`, so the funnel is built from views (one per URL path) and RUM's automatic actions (`click on button on /upload` and so on). The call is kept for tenants that record them.
- Express proxies `/api/*` and forwards trace headers untouched.

## 7. Toggle API and scenarios

All services expose `GET /control/toggles` and `PUT /control/toggles` with JSON state held in memory (resets on restart, defaults from env).

| Service | Toggle | Values | Effect |
|---|---|---|---|
| `legacy-stub` | `mode` | normal, slow, brownout | normal: 50-150 ms. slow: 2-5 s. brownout: slow plus 15% HTTP 500 |
| `legacy-stub` | `pool_threads` | 1 to 64 | Resizes the Tomcat worker pool at runtime (no restart needed) |
| `claims-api` | `eligibility_release` | v1, v2_bad | v2_bad returns wrong decisions for one age band, adds latency, raises a fraction of errors. Toggle flip logs a deployment line that OpenPipeline turns into a Dynatrace deployment event |
| `claims-api` | `upload_fault` | none, slow, error | slow: 3-8 s. error: 15% HTTP 500 on upload |
| `claims-api` | `log_pii` | on, off | on: logs TFN and Medicare number in clear in request and error logs |
| `llm-gateway` | `latency` | normal, slow | normal: 300-900 ms. slow: 6-12 s |
| `llm-gateway` | `provider_errors`, `provider_error_rate` | none, 429, 503, and 0 to 100 | Percentage configurable, default 30% |
| `llm-gateway` | `guardrails` | on, off | on: injection blocked. off: injection fails open and returns another citizen's claim summary from seed data |
| `claims-api` | `capture_content` | on, off | on: populate `gen_ai.input.messages` and `gen_ai.output.messages` on the `chat` span, including any PII. The client decides what to record, so this toggle lives on `claims-api` |
| `llm-gateway` | `response_mode` | grounded, hallucinated, verbose | hallucinated: wrong amount and a non-existent policy clause. verbose: long response, high token counts |
| `payment-worker` | `concurrency`, `processing_delay_ms` | integer | Controls drain rate |

### Named scenarios (`scenarios/scenarios.yaml`, applied by `scenarios/run_scenario.py`)

| Scenario | Toggle changes | Load profile | Dynatrace story |
|---|---|---|---|
| `baseline` | All defaults | Steady low | Baselines, healthy SLOs |
| `monday_peak` | Legacy `slow`, worker concurrency 1 | Peak wave | Davis root cause on legacy tier, SLO burn on claim submission, queue growth |
| `bad_release` | `eligibility_release=v2_bad` | Steady medium | Deployment event correlation, problem on claims-api |
| `upload_dropoff` | `upload_fault=slow` | Playwright abandoner plus completer | RUM funnel drop-off, Session Replay |
| `ai_injection` | `guardrails=off` | Assistant user (injection prompts) | AI security signal, data exposure |
| `ai_pii` | `capture_content=on`, `log_pii=on` | Assistant user (PII prompts) | Log and span masking via OpenPipeline |
| `ai_cost_spike` | `response_mode=verbose` | Assistant user | Token and cost tracking |
| `ai_hallucination` | `response_mode=hallucinated`, `guardrails=off` | Assistant user | Evaluation failures. Guardrails are off because the grounding check would otherwise block the wrong amount |
| `provider_outage` | `provider_errors=503` | Assistant user | Error rate, dependency health |
| `show_prompts` | `capture_content=on` | Assistant user | Prompts and answers fill the AI Observability Prompts view. Not a fault scenario |
| `reset` | All defaults | None | Return to baseline |

`run_scenario.py` takes a scenario name, calls each service's toggle API, and starts or switches the Locust profile through its control endpoint. It must be idempotent.

## 8. Telemetry specification

### 8.1 Instrumentation model

| Layer | Method |
|---|---|
| HTTP, JVM, process for Node and Java (`web`, `legacy-stub`) | OneAgent via Operator injection (`applicationMonitoring` on the lab k3s cluster). No manual spans for these |
| HTTP, Postgres and outbound calls for the Python services (`claims-api`, `payment-worker`, `llm-gateway`) | OpenTelemetry SDK with the FastAPI, urllib and psycopg instrumentation libraries, exported over OTLP/HTTP to the in-cluster `telemetry-ingest` collector (`http://telemetry-ingest.dynatrace:4318`, no token needed from inside the cluster, verified). Reason: in the lab tenant the OneAgent Python sensors for FastAPI, Starlette and psycopg2 are disabled and there is no psycopg 3 sensor. Tracing export is off when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset (Compose) |
| Trace context across OneAgent and OTel | W3C `traceparent` and `tracestate`. Verified: one trace spans web (OneAgent), claims-api and payment-worker (OTel) and legacy-stub (OneAgent). If the OneAgent Python sensors are ever enabled, expect duplicate spans from the Python services |
| Manual spans | OpenTelemetry API only where OneAgent has no visibility: payment worker consumer span, assistant orchestration, tool execution, gateway `chat` and guardrail spans |
| Trace context via queue | W3C `traceparent` and `tracestate` stored in `payment_queue` at submit, restored in worker |
| Frontend | Dynatrace RUM JavaScript snippet |
| OTLP on k8s | The DynaKube `telemetryIngest` exposes an in-cluster OTLP endpoint (service `telemetry-ingest`). Prefer this over the tenant OTLP endpoint on k8s, since the collector holds the token. Endpoint and port to be verified in Phase 2 |
| Fallback if OneAgent does not pick up manual OTel spans | Export OTLP directly from the affected services to the tenant OTLP endpoint (see section 14, item 2) |

### 8.2 GenAI span schema (verified against current Dynatrace documentation)

Dynatrace reads `gen_ai.*` attributes natively over OTLP with no transformation.

**`claims-api`: one `chat {model}` span per completion, kind CLIENT (client-side, as client instrumentation does).** The gateway does not emit `chat` spans or GenAI metrics, so tokens and cost are counted once. Content filter results are read from the gateway response and set on this span.

| Attribute | Value |
|---|---|
| `gen_ai.operation.name` | `chat` (required) |
| `gen_ai.provider.name` | See section 14, item 3 (required) |
| `gen_ai.request.model` | Required |
| `gen_ai.response.model` | Required |
| `gen_ai.response.id` | Generated id |
| `gen_ai.response.finish_reasons` | `stop`, `length`, `tool_calls` or `content_filter` |
| `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | Taken from the gateway response `usage`, which the gateway computes with a simple token estimator (whitespace split times a fixed factor). Verbose mode multiplies output |
| `gen_ai.request.temperature`, `gen_ai.request.max_tokens` | Fixed values |
| `gen_ai.conversation.id` | From `X-Conversation-Id` |
| `gen_ai.input.messages`, `gen_ai.output.messages` | Only when `capture_content=on` (opt-in by design, a toggle on `claims-api`). Structured message format with text, tool_call and tool_call_response parts. Verified accepted by the AI Observability Prompts view |
| `gen_ai.prompt.prompt_filter_results`, `gen_ai.completion.content_filter_results` | JSON strings in the Azure OpenAI content filter shape, copied from the gateway response. These drive the provider-specific AI Observability guardrail tiles (verified: guardrail activations appear) |
| Error handling | `error.type` on the span and on the duration metric when the gateway returns 429 or 503 (Phase 4) |

**`claims-api`: agent and tool spans**

| Span | Attributes |
|---|---|
| `invoke_agent claims-assistant` (INTERNAL) | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name=claims-assistant`, `gen_ai.agent.id`, `gen_ai.conversation.id`, `gen_ai.provider.name` |
| `execute_tool check_eligibility` (INTERNAL) | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name=check_eligibility`, `gen_ai.tool.description` |

**`llm-gateway`: HTTP server span, guardrail spans (input check and output check)**

| Attribute | Value |
|---|---|
| `gen_ai.guardrail.name` | `prompt_injection_check`, `pii_check`, `grounding_check` |
| `demo.guardrail.action` | `allow` or `block` (custom namespace, not a standard attribute) |
| `demo.guardrail.reason` | Short code |

The custom `gen_ai.guardrail.*` and `demo.guardrail.*` spans are useful in DQL but do not drive the AI Observability guardrail tiles. Those read provider-specific attributes (Azure OpenAI content filter results, set on the `chat` span). See section 14, item 4.

### 8.3 GenAI metrics (required, not derived from spans)

Dynatrace documentation states these are metric instruments that the instrumentation must emit. `claims-api` needs a MeterProvider (delta temporality for histograms). The gateway does not emit them.

| Metric | Type | Attributes |
|---|---|---|
| `gen_ai.client.token.usage` | Histogram | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.token.type` (input or output), `gen_ai.request.model`, `gen_ai.response.model` |
| `gen_ai.client.operation.duration` | Histogram (seconds) | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model` |

### 8.4 Conversation and session linking

- Frontend generates or reads the session id, sends it as `conversation_id`.
- `claims-api` sets `gen_ai.conversation.id` on the `invoke_agent` span and forwards it to the gateway in `X-Conversation-Id`.
- `claims-api` sets it on its HTTP server span, `invoke_agent`, `chat` and `execute_tool` spans. The gateway sets it on its server span and guardrail spans.
- Dynatrace propagates `dt.rum.session.id` to backend spans from the RUM tracestate. Dynatrace documentation describes aligning `gen_ai.conversation.id` with the RUM session id for the frontend link in distributed traces.

### 8.5 Evaluation results

Dynatrace stores evaluation results as business events with `event.type == "gen_ai.evaluation.result"`, carrying `gen_ai.evaluation.name`, `gen_ai.evaluation.score.value`, `gen_ai.evaluation.score.label` (pass or fail), an explanation and the source trace id. Production path is the dt-evals toolkit or Dynatrace-side evaluation with a configured judge LLM. A mock gateway cannot act as judge. See section 14, item 1.

### 8.6 Business events

| Event type | Emitted by | Key fields |
|---|---|---|
| `claim.draft_created` | claims-api | claim_id, payment_type |
| `claim.eligibility_checked` | claims-api | claim_id, decision, duration_ms |
| `claim.document_uploaded` | claims-api | claim_id, size_bytes |
| `claim.submitted` | claims-api | claim_id, payment_type |
| `claim.payment_posted` | payment-worker | claim_id, amount_cents, queue_wait_ms |
| `claim.payment_failed` | payment-worker | claim_id, error |

Abandonment is derived in DQL as drafts without a later `claim.submitted`. Transport: none in the apps. Each service logs a structured JSON line with a `business_event` field and the key values, and an OpenPipeline logs pipeline in the tenant parses the JSON and extracts the business events (definition in `docs/openpipeline/`, steps in `docs/dynatrace-config.md`). This needs no ingest token and keeps the apps vendor-neutral.

### 8.7 Logs

- JSON to stdout with trace and span ids included.
- `claims-api` with `log_pii=on` writes TFN and Medicare number in clear on login and eligibility paths.
- Masking is demonstrated by Dynatrace OpenPipeline rules, not by application code. Rules are documented in `docs/dynatrace-config.md`.

### 8.8 Deployment event

When `eligibility_release` changes, `claims-api` logs a structured line with `deployment_event`, `deployment_name`, `release_version` and `previous_version`. An OpenPipeline Davis event processor in the tenant turns it into a `CUSTOM_DEPLOYMENT` event (definition in `docs/openpipeline/`). No token is needed. Verification status is in PROGRESS.md.

## 9. Frontend notes

- Keep markup plain and accessible. A government-style layout (header band, step indicator, plain forms) is enough. No design system dependency.
- Step indicator shows steps 1 to 5 so funnel drop-off is visible in Session Replay.
- Assistant widget shows a banner when a response is flagged by a guardrail.
- Footer text: "Demonstration system. Fictional policy and data."

## 10. Load generation

### 10.1 Locust (standing container)

| User class | Weight | Behaviour |
|---|---|---|
| `Completer` | 5 | login, create claim, eligibility, upload, submit, poll status |
| `Abandoner` | 2 | login, create claim, eligibility, stops before upload (HTTP level, trace and business event signal only) |
| `AssistantUser` | 2 | Cycles scripted prompts: eligibility question, general question, injection attempt, PII-bearing prompt, verbose request |

| Profile | Shape | Selection |
|---|---|---|
| `baseline` | 3 to 5 concurrent users, constant | Default |
| `peak` | Ramp to 60 users over 3 minutes, hold 10 minutes, ramp down | Custom `LoadTestShape` |

- Profile chosen by env `LOAD_PROFILE` at start, switchable at runtime through the Locust web UI or a small control call used by `run_scenario.py`.
- Credentials loaded from the seed CSV mounted as a volume.
- Request names set explicitly so Dynatrace and Locust stats align.
- Think time between steps randomised (1 to 4 s).
- Starting user counts are assumptions. Adjust after the first run on the lab node.

### 10.2 Playwright (on demand)

| Profile | Behaviour |
|---|---|
| `completer` | Full journey in headless Chromium |
| `abandoner` | Leaves at the upload step |
| `assistant` | Opens widget, sends two prompts |

- CLI parameters: base URL, profile, number of sessions, max concurrency (default 3).
- Implementation: `playwright-core` driving the installed Google Chrome (no large browser download), `--bundled` switches to Playwright's own Chromium. Each session is a fresh browser context so RUM records a new session.
- Run from laptop or a one-off container. Requires frontend reachable via NodePort, ingress or port-forward.
- Not part of `docker-compose.yml` standing services. Provide a separate `make browser-load` target.

### 10.3 Dynatrace Synthetic

Out of repo scope. Browser monitors configured separately in the tenant. Reachability of the lab from a synthetic location is unverified.

## 11. Deployment

### Docker Compose (dev)

- One service per container in section 3, plus `postgres` and `locust`.
- `make up`, `make down`, `make seed`, `make scenario NAME=monday_peak`, `make logs`, `make browser-load`.
- Healthchecks and `depends_on` conditions so the startup order is Postgres, then seed, then services.

### k3s (lab)

- Namespace `gov-demo`. One Deployment and ClusterIP Service per app. NodePort or Ingress for `web` and Locust UI only.
- Resource requests and limits set. Starting assumptions (not measured): Python services 128 to 256 Mi each, `web` 128 Mi, Postgres 256 Mi, Java stub 512 Mi limit with 384m heap, Locust 256 Mi. Adjust after measurement.
- Dynatrace injection through the existing Operator and DynaKube, namespace-selected. Use only the labels and annotations required by the installed Operator version. Confirm against the lab's DynaKube configuration.
- Secrets (control token, Dynatrace tokens, DB password) via Kubernetes Secrets. Do not commit values.
- `kustomization.yaml` so `kubectl apply -k k8s/` deploys everything.

### Disk and data hygiene

The stack runs continuously with load, so growth must be bounded:

- A retention job deletes claims, documents, queue rows and payments older than `RETENTION_HOURS` (default 6) every 15 minutes (CronJob on k3s, looping service in Compose). Seeded citizens stay.
- Services log structured events and errors, not every request, unless `ACCESS_LOG=on`. Compose rotates container logs.
- `make disk` reports usage and `make prune` reclaims build cache and dangling images.

### Secrets and tenant settings

- Tenant settings and tokens live in `secrets/*.env`, created from committed `secrets/*.env.example` templates. Real files are gitignored and mode 600. Nobody pastes values into chat.
- `make secrets-init` creates missing files from templates. `make secrets-check` reports which keys are set or empty, by name only, never values.
- Compose loads `secrets/dynatrace.env` through `env_file` (optional, so the stack still runs without it). On k8s, Secrets are created from the same files with `kubectl create secret generic --from-env-file`, never stored in manifests.
- The same pattern is used for any other vendor (for example Bindplane): add `secrets/<name>.env.example` and the existing targets pick it up.
- The DynaKube for the lab cluster is kept in `secrets/` because it embeds tokens.
- Tenant for this build is SaaS, `imb05402.live.dynatrace.com`. The lab cluster is Rancher Desktop (k3s), with a DynaKube `dev-rancher-k8s` using `cloudNativeFullStack` and `telemetryIngest` (OTLP) enabled.

## 12. Build phases and acceptance checks

| Phase | Scope | Acceptance |
|---|---|---|
| 0 | Repo skeleton, Compose, Postgres schema, seed, `/healthz` on all services, `CLAUDE.md` | `make up` brings all containers healthy. Seed produces 500 citizens and a credentials CSV |
| 1 | Happy path: web, claims-api, legacy-stub, queue, payment-worker | One claim goes from login to `paid` through the UI. Payment row exists. Queue row ends `done` |
| 2 | Telemetry core: queue trace propagation, business events, structured logs, RUM via OneAgent auto-injection | One submitted claim yields a single trace spanning web, claims-api, queue consumer, legacy-stub. Business events visible in tenant. Logs carry trace ids |
| 3 | `llm-gateway` and assistant | Eligibility question returns a grounded answer via tool call. `chat`, `invoke_agent`, `execute_tool` spans and both GenAI metrics visible in AI Observability. Token counts present |
| 4 | Toggles and scenarios | Each scenario in section 7 applies and resets cleanly. Each toggle changes observable behaviour within one request |
| 5 | Locust | `baseline` and `peak` run. `peak` produces visible legacy queueing and queue growth. Assistant users exercise injection and PII prompts |
| 6 | Playwright | Completer and abandoner sessions appear in RUM with funnel drop-off at upload |
| 7 | k3s manifests | `kubectl apply -k k8s/` deploys the stack. Injection confirmed on all five services |
| 8 | Docs | `runbook.md` has a demo script and expected Dynatrace view per scenario. `dynatrace-config.md` lists tenant-side configuration |

## 13. Tenant-side configuration (documented, not built in repo)

| Item | Purpose |
|---|---|
| SLOs | Claim submission availability and latency, assistant latency |
| OpenPipeline rules | Mask TFN and Medicare patterns in logs and span attributes |
| Davis anomaly detection tuning | Ensure peak scenario raises a problem in demo timeframe |
| Dashboard or Notebook | Citizen journey, queue depth, AI usage and cost |
| RUM application and funnel | Steps 1 to 5 |
| Tokens | Scopes for OTLP ingest, metrics ingest, logs ingest, business events ingest, events ingest. Confirm exact scope names in current documentation |

## 14. Open items and unverified assumptions

| # | Item | Status | Default if no decision |
|---|---|---|---|
| 1 | Evaluation path for the hallucination scenario | Decision needed. Judge LLM cannot be the mock | Emit clearly labelled synthetic `gen_ai.evaluation.result` business events from the gateway (`demo.synthetic=true`). Upgrade to dt-evals with a real judge later |
| 2 | Whether OneAgent captures manual OTel spans from the Python services in this lab | Resolved for the lab: OneAgent does not trace the Python services, OTel does the work and the traces join | Python services export OTLP via `telemetry-ingest` (see section 8.1) |
| 3 | Provider and model naming for the mock, and whether Dynatrace cost views compute cost for it | Unverified | Use a plausible provider and model name, label the mock clearly in the README. If cost is not calculated, compute cost from token counts in DQL |
| 4 | Native guardrail span shape in the AI Observability guardrails view | Unverified. `gen_ai.guardrail.name` appears in Dynatrace attribute mappings, view requirements not confirmed | Build as specified in 8.2, adjust after viewing the tenant |
| 5 | Transport and token scopes for deployment events and business events | Business events resolved: extracted from logs by OpenPipeline, no token. Deployment events (Phase 4) still need the events API and a token with `events.ingest`, to confirm | Decide the deployment event path in Phase 4 |
| 6 | Runtime vulnerability detection of the chosen old library | Unverified | Test in phase 1. Swap library if not flagged |
| 7 | RUM session id retrieval from the browser | Per Dynatrace conversation tracking documentation a session id accessor exists. Exact API not confirmed | Fall back to a generated UUID |
| 8 | Lab node capacity for 7 standing containers plus Java | Not measured | Start with limits in section 11 and adjust |

## 15. Out of scope

- Real LLM calls, real identity provider, real payments
- Dynatrace Synthetic monitor creation
- Tenant configuration automation
- Multi-tenant or HA concerns
- Any real government branding, data or policy
