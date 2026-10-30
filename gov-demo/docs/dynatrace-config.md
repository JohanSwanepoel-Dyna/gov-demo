# Tenant-side configuration

What the demo needs in the Dynatrace tenant, and its status. The lab tenant is SaaS. Items marked applied were done and checked. Items marked not built are documented here but not created, as the spec intends (tenant configuration is not automated in this repo).

## Checklist

| # | Item | Purpose | Status |
|---|---|---|---|
| 1 | DynaKube with `applicationMonitoring` and `telemetryIngest` | OneAgent injection for Node and Java, OTLP endpoint for the Python services | Applied |
| 2 | API tokens for the app | Ingest from the app | Not needed |
| 3 | OpenPipeline logs pipeline and routing entry | Business events and the deployment event from logs | Applied and verified |
| 4 | OneAgent Python sensors | Leave disabled | As found |
| 5 | RUM application and funnel | Browser sessions, funnel at the upload step | Auto-created, funnel verified |
| 6 | Masking rule for TFN and Medicare | Show masking in logs and prompts | Not built, proposal below |
| 7 | SLOs | Claim submission and assistant | Not built, proposals below |
| 8 | Davis anomaly detection tuning | A clean problem for the peak scenario | Not done |
| 9 | Dashboard | Journey, payments, AI usage and cost, RUM funnel, change | Built, see section 9 |
| 10 | Vulnerability detection of the old log4j | Security story | Not confirmed |

## 1. DynaKube

The cluster uses the Dynatrace Operator with a DynaKube in the `dynatrace` namespace. The file lives in `secrets/` because it embeds tokens and is gitignored. The settings that matter:

```yaml
spec:
  apiUrl: https://<environment-id>.live.dynatrace.com/api
  oneAgent:
    hostGroup: development-desktop
    applicationMonitoring: {}      # injection into pods, no host agent
  telemetryIngest:
    protocols: [otlp]
    serviceName: telemetry-ingest  # in-cluster OTLP, http://telemetry-ingest.dynatrace:4318
```

Why `applicationMonitoring` and not `cloudNativeFullStack`: on Rancher Desktop the node is Alpine Linux (musl). The OneAgent host agent needs the glibc loader `/lib/ld-linux-aarch64.so.1`, which the node does not have, so the OneAgent DaemonSet crash-looped with `execv ... oneagentwatchdog: No such file or directory`. Pod injection runs inside each container, so it does not depend on the node. Host metrics for the VM are not collected. Namespaces are selected automatically (no selector), so `gov-demo` is injected.

Check: `kubectl get dynakube -n dynatrace` shows Running, and pods in `gov-demo` carry the annotation `dynakube.dynatrace.com/injected=true`.

## 2. Tokens

The app needs no Dynatrace token. Traces, metrics and logs go through the in-cluster collector that the DynaKube creates, and business events and the deployment event come from OpenPipeline, not an ingest API. The only tokens in play are the Operator's own, in the `dynatrace` namespace.

## 3. OpenPipeline: business events and the deployment event

The apps log structured JSON. Lines that represent a business event carry a `business_event` field:

| business_event | Emitted by | Other fields |
|---|---|---|
| `claim.draft_created` | claims-api | claim_id, payment_type |
| `claim.eligibility_checked` | claims-api | claim_id, decision, duration_ms |
| `claim.document_uploaded` | claims-api | claim_id, size_bytes |
| `claim.submitted` | claims-api | claim_id, payment_type, reference |
| `claim.payment_posted` | payment-worker | claim_id, amount_cents, queue_wait_ms |
| `claim.payment_failed` | payment-worker | claim_id, error (final failure only) |

OneAgent log ingestion keeps the JSON in `content` and lifts only `trace_id` and `span_id` to attributes, so the pipeline first parses the JSON, then extracts one business event per type. The fields `attempts` and `final` of `claim.payment_failed` are logged but not parsed yet, add them to the parse step if you want them as event fields.

1. Create the pipeline: `dtctl apply -f docs/openpipeline/gov-demo-logs-pipeline.yaml`. To update it later, export it with `dtctl get settings --schema builtin:openpipeline.logs.pipelines -o json`, add its `objectId` to the file, and apply that file.
2. Add one entry to the logs routing table (Settings, OpenPipeline, Logs, Dynamic routing), after any broader rules:
   - Matcher: `matchesValue(k8s.namespace.name, "gov-demo") and (matchesPhrase(content, "business_event") or matchesPhrase(content, "deployment_event"))`
   - Pipeline: `gov-demo business events` (custom id `pipeline_gov_demo_bizevents`)

   The routing table is one shared settings object, so read it, append the entry, and apply it back. Keep a copy of the original first.
3. Check:
```
fetch bizevents, from: now()-15m | filter event.provider == "dcs.carer-portal" | summarize n = count(), by: {event.type}
```

OpenPipeline matchers do not allow `contains()`. Use `matchesPhrase()` there. In `fetch` queries `contains()` is fine and `matchesPhrase()` does not match inside JSON log text, so use `contains()` to search log content.

Deployment event: when `eligibility_release` changes, claims-api logs a line with `deployment_event`, `deployment_name`, `release_version` and `previous_version`. The same pipeline has a Davis event processor that creates a `CUSTOM_DEPLOYMENT` event attached to the claims-api service. Verify with:
```
fetch events, from: now()-30m | filter event.type == "CUSTOM_DEPLOYMENT"
```

Abandonment is derived in DQL as drafts without a later submit, see the runbook.

## 4. OneAgent Python sensors

In the lab tenant the OneAgent features `SENSOR_PYTHON_FASTAPI`, `SENSOR_PYTHON_STARLETTE` and `SENSOR_PYTHON_PSYCOPG2` are disabled, and there is no psycopg 3 sensor. The Python services (claims-api, payment-worker, llm-gateway) are therefore instrumented with OpenTelemetry and export to the in-cluster collector. Do not enable the Python sensors for this demo, it would produce duplicate spans next to the OpenTelemetry ones.

The Python services drop the Dynatrace entry of the incoming `tracestate` header (a key ending in `@dt`). Without that, the OneAgent Java stub took its parent from that entry and appeared to be called by `web` instead of by claims-api.

## 5. RUM

OneAgent injects the RUM JavaScript into the pages served by `web` (for browser-like requests, curl does not show it). Dynatrace created the application "Government Claim Process" (id `APPLICATION-EA7C4B59F27D43EB`), its frontend name shows as `My_web_application`, and you can rename it. A second application, "Government Claims Process", exists and receives no data, delete it if you do not need it.

The funnel is built from views: each step of the journey is its own URL path (`/login`, `/payment-type`, `/details`, `/eligibility`, `/upload`, `/review`, `/status`). Hash routes were tried first and RUM recorded a single view. RUM's automatic actions (`click on button on /upload`) show the same transitions. The classic custom actions `step_*` are sent by the page but this tenant's RUM does not store them.

Define the funnel in the RUM application on the seven views. Session Replay was not verified, enable it for the application if you want it.

Frontend to backend linking works with the OpenTelemetry services: browser requests carry W3C trace context and the same trace id continues through `web` into claims-api.

## 6. Masking rule (not built)

The `ai_pii` scenario writes TFN and Medicare numbers in clear into claims-api log lines (`"tfn": "..."`, `"medicare_number": "..."`) and records prompts with a TFN into `gen_ai.input.messages`. Masking is meant to be shown with OpenPipeline, not application code.

Proposal, untested: add a DQL processor to the processing stage of the logs pipeline that replaces nine and ten digit numbers in `content` and in the parsed fields, and add the same masking for span attributes in the spans pipeline. Check the available DQL string functions in the current documentation before writing it, and test on `ai_pii` data: the sign-in log line and the prompt with TFN `123456782` are the two things to see masked.

## 7. SLOs (not built)

Proposed definitions, to be created in the tenant:

- Claim submission availability: share of `POST /api/claims/{claim_id}/submit` server spans that succeed. Target 99 percent.
- Claim submission latency: p95 of the same spans under 1 second.
- Payment completion: share of submitted claims that end in `claim.payment_posted` rather than `claim.payment_failed` (business events). The `monday_peak` scenario burns this one.
- Assistant latency: p95 of the `chat` spans of claims-api under 2 seconds.

## 8. Davis anomaly detection

Not tuned. During the lab peak runs Davis opened 9 problems on the demo services in 6 hours, mainly "Response time degradation" plus one "Failure rate increase". The root cause shown was `web` or empty, not the legacy stub. If the demo story needs "Davis points at the legacy tier", tune the detection on the legacy service and check a live problem first.

## 9. Dashboard

Built: "Carer Support Portal demo" (id `fff6ca52-9dac-495c-91db-2f02b18cc977`, owner is the account that applied it), https://imb05402.apps.dynatrace.com/ui/apps/dynatrace.dashboards/dashboard/fff6ca52-9dac-495c-91db-2f02b18cc977. 22 tiles, 18 of them data tiles, all queries checked against the tenant before applying.

- Headline numbers: claims submitted, payments posted, payments failed, average queue wait, tokens used, prompts blocked by guardrails.
- Claims and payments: journey events by step, claims over time (paid in the good colour, failed in the critical colour), payment queue wait (average and p95), failed payments by error, server response time p95 by service.
- AI assistant: tokens by type, chat completion latency (p50 and p95), guardrail outcome per chat, chat errors by type.
- Experience and change: RUM funnel (sessions per step), deployment events, Davis problems on the demo services.

The tiles follow the dashboard timeframe (they carry no timeframe of their own), so pick the window with the selector, for example the last 2 hours. Not on the dashboard: queue depth (it lives in the `payment_queue` table, not in the tenant) and Locust's own request rate.

The dashboard is defined in code: `docs/dashboards/build_dashboard.py` writes `docs/dashboards/gov-demo.json`. `python3 docs/dashboards/build_dashboard.py --check` runs every tile query once against the tenant (one `dtctl` call at a time). `dtctl apply -f docs/dashboards/gov-demo.json` updates the dashboard in place, because the file carries its id. Not checked: how the tiles look in the browser, the layout and colours were built from the structure of an existing dashboard but not seen rendered.

## 10. Security

The legacy stub deliberately loads Log4j 2.14.1 (CVE-2021-44228), confirmed loaded at runtime. Whether the tenant flags it as a vulnerability is not confirmed: a DQL search of security events found nothing, which may be the wrong field names or runtime vulnerability analytics not being active under `applicationMonitoring`. Check Security, Vulnerabilities for `legacy-stub` in the UI. The stack must stay off the internet either way.
