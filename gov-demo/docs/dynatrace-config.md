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
| 6 | Masking rule for TFN and Medicare | Show masking in logs and prompts | Applied and verified for logs, business events and recorded prompts |
| 7 | SLOs | Claim submission, eligibility, payment completion, assistant | Built, six SLOs, see section 7 |
| 8 | Davis anomaly detection tuning | A clean problem for the peak scenario | Decided not to tune, the SLOs carry the burn story (see section 8) |
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

## 6. Masking TFN and Medicare

The `ai_pii` scenario writes TFN and Medicare numbers in clear into claims-api log lines (`"tfn": "..."`, `"medicare_number": "..."`) and records prompts containing a TFN into `gen_ai.input.messages`. Masking happens in OpenPipeline at ingest, not in application code.

How: a DQL processor using `replacePattern` with DPL patterns anchored on a label, so only the digits are replaced and the rest of the line is untouched:

| Pattern (DPL) | Masks |
|---|---|
| `<<'"tfn": "' DIGIT{9}` | the `tfn` field of a log line |
| `<<'"medicare_number": "' DIGIT{10}` | the `medicare_number` field |
| `<<('TFN is ' \| 'TFN: ' \| 'TFN ' \| 'tfn is ' \| 'tfn ') DIGIT{9}` | free text such as "My TFN is 123456782" |
| `DIGIT{3} ' ' DIGIT{3} ' ' DIGIT{3}` | a TFN written as 123 456 782 |

Why anchored: a bare nine digit pattern was tested and rejected. It matched digits inside the hex `trace_id` (breaking trace correlation) and left the last digit of a ten digit Medicare number visible. Tested read-only with DQL on real data before it went into a pipeline. In the replacement the matched digits become `[masked]`.

Logs (applied and verified): the masking processor is the first step of the `gov-demo business events` pipeline, so it runs before the parse step and before business events are extracted. The routing entry also sends lines containing `tfn` or `medicare_number` to that pipeline (sign-in lines have no `business_event`). Result with `ai_pii` on: 6 of 6 new log lines arrived with `"tfn": "[masked]"`, none in clear, all kept their `trace_id`, and the business events built from them carry the masked content (3 of 3). Check:
```
fetch logs, from: now()-30m
| filter k8s.workload.name == "claims-api" and contains(content, "\"tfn\"")
| summarize lines = count(), masked = countIf(contains(content, "\"tfn\": \"[masked]\"")), clear = countIf(not contains(content, "\"tfn\": \"[masked]\""))
```

Spans (applied and verified): the pipeline `pipeline_gov_demo_spans` (`docs/openpipeline/gov-demo-spans-pipeline.yaml`) masks `gen_ai.input.messages` and `gen_ai.output.messages`, and a routing entry sends the claims-api spans that carry them to it (`docs/openpipeline/gov-demo-spans-routing.yaml`, the pipelineId in that file is a placeholder, use the objectId from `dtctl get settings --schema builtin:openpipeline.spans.pipelines -o json`). The spans routing is a shared tenant setting that did not exist before, it holds this one entry. Result: 28 of 28 new chat spans with a TFN in the prompt arrived masked, none in clear, and a span compared before and after the routing had the same 60 attributes (service entity, `dt.smartscape.gen_ai.*`, tokens and finish reason all intact), so AI Observability is not affected. A recorded prompt now reads `My TFN is [masked]`. Check:
```
fetch spans, from: now()-30m
| filter service.name == "claims-api" and startsWith(toString(span.name), "chat ") and isNotNull(gen_ai.input.messages)
| summarize chats = count(), masked = countIf(contains(toString(gen_ai.input.messages), "TFN is [masked]")), clear = countIf(contains(toString(gen_ai.input.messages), "123456782"))
```
Roll back by deleting the routing entry (Settings, OpenPipeline, Spans, Dynamic routing) or the whole spans routing object. Spans not matching the entry are not affected.

Limits: only the labelled forms above are masked. "my tax file number is 123456782" or a bare number is not. Medicare is masked only in the labelled log field. Lines ingested before the rule keep their clear values until the bucket retention expires (this lab only holds synthetic data). Turn `log_pii` and prompt recording off (`make scenario NAME=baseline`) when you are not demonstrating.

## 7. SLOs

Six SLOs, defined in `docs/slos/*.yaml` and created with `dtctl create slo -f docs/slos/<name>.yaml`. Each one is a DQL timeseries that returns a percentage called `sli`, evaluated over the last 2 hours so a burn shows up quickly in a demo (the tenant allows one window per SLO, edit `timeframeFrom` to `now-7d` for a realistic window). All six indicators were tested as queries before they were created.

| SLO | Indicator | Target (warning) | Burns in |
|---|---|---|---|
| Claim submission availability | Submit requests without a 5xx | 99 (99.5) | Stays green, submitting only queues the payment |
| Claim submission latency under 1 s | Submit requests under 1 s | 95 (97) | Stays green |
| Eligibility check latency under 1 s | Eligibility checks under 1 s (a synchronous call through the legacy stub) | 95 (97) | monday_peak, bad_release |
| Payment completion | Payments posted rather than failed (business events) | 99 (99.5) | monday_peak |
| Assistant availability | Model calls without an error | 99 (99.5) | provider_outage |
| Assistant latency under 2 s | Model calls under 2 s | 95 (97) | Only with the gateway latency toggle set to slow |

The submission SLOs were in the original spec, but claim submission does not burn in `monday_peak`: the submit call only inserts a queue row and the slow work happens afterwards. The eligibility, payment and assistant availability SLOs were added because those are the ones the scenarios actually burn, and the submission SLOs stay as green controls.

Evaluate one: `dtctl exec slo <id>`. First evaluation, right after creating them (the earlier peak runs were still inside the window): payment completion FAILURE at 98.36 percent, eligibility latency FAILURE at 75.86 percent, the other four SUCCESS. They recover on their own once the window has passed the peak. After a demo, `make scenario NAME=baseline` and wait for the 2 hour window to clear, or accept the red ones as the "after the incident" view.

## 8. Davis anomaly detection (decided: not tuned)

Decision: the detection settings in the tenant are left alone, and the SLOs (section 7) are the way to show damage and burn. What led to it, from the lab runs:

- Davis does raise problems for `monday_peak`, but late (about 10 minutes into the peak in the last run) and fragmented: separate problems for `web` and `claims-api`, none for the legacy stub, which is the real bottleneck (its learned baseline probably absorbed the slow behaviour after several peaks, not proven).
- The `web` problems end at the placeholder entity "Requests to unmonitored hosts" (the problem records carry it as `root_cause_entity_id`). OneAgent on `web` sees its calls to `claims-api` as calls to an unmonitored host because the Python services are OpenTelemetry only. The `claims-api` problems relate only to the cloud application, namespace and cluster, so nothing links them to `web`'s.
- The platform topology (`smartscapeEdges "calls"`) has the right service to service links, plus a few stale wrong ones from before the trace parent fix (they age out). Davis problem correlation still ended at the placeholder, so it appears to follow the OneAgent built call graph. This is a hypothesis, Davis internals were not visible.
- Tuning the auto-adaptive sensitivity would tune to noise: the laptop runs the demo in bursts and sleeps, so baselines are patchy.

If this is revisited, there are two real options, neither tried:
- Enable the OneAgent Python sensors for FastAPI and Starlette (a tenant-wide OneAgent feature). `claims-api` becomes monitored, the placeholder should go and Davis could follow `web` to `claims-api` to the stub. Cost: possible duplicate spans next to the OpenTelemetry ones and a muddier "OneAgent plus OTel" story. Test on one `monday_peak` run.
- Fixed threshold rules scoped to the five demo services (for example eligibility response time over 1 second for 3 of 5 minutes, any failed payment). Deterministic on any machine because the injected faults are large, but it does not connect the chain, `web` would still end at the placeholder.

On a machine that runs always-on, let the demo sit at baseline load for a day or two before a customer demo so Davis has a baseline, and still do not rely on it for the story.

## 9. Dashboard

Built: "Carer Support Portal demo" (id `fff6ca52-9dac-495c-91db-2f02b18cc977`, owner is the account that applied it), https://imb05402.apps.dynatrace.com/ui/apps/dynatrace.dashboards/dashboard/fff6ca52-9dac-495c-91db-2f02b18cc977. 32 tiles, 27 of them data tiles, all queries checked against the tenant before applying.

- Headline numbers: claims submitted, payments posted, payments failed, average queue wait, tokens used, prompts blocked by guardrails.
- Claims and payments: journey events by step, claims over time (paid in the good colour, failed in the critical colour), payment queue wait (average and p95), failed payments by error, server response time p95 by service.
- AI assistant: tokens by type, chat completion latency (p50 and p95), guardrail outcome per chat, chat errors by type.
- Web experience (browser sessions, from RUM): Core Web Vitals as p75 (largest contentful paint, interaction to next paint, cumulative layout shift) plus time to first byte, journey completion rate and abandonment rate, the RUM funnel (sessions per step), the furthest step each session reached (the abandonment histogram), web vitals over time, and browser errors over time (JavaScript, HTTP 4xx and 5xx).
- Change and problems: deployment events and the Davis problems on the demo services.

Reading the web tiles: completion rate is the share of sessions that reached `/login` and went on to `/status`. Abandonment is the rest, and "furthest step reached" shows where they stopped (ineligible citizens stop at 4 eligibility, abandoners at 5 upload, chat-only sessions at 2 payment-type). These cover browser sessions only, Locust is protocol level and has no RUM sessions. INP often reads 0 in the lab because scripted browsers make few interactions, so treat it as a placeholder until real clicking happens.

The tiles follow the dashboard timeframe (they carry no timeframe of their own), so pick the window with the selector, for example the last 2 hours. Not on the dashboard: queue depth (it lives in the `payment_queue` table, not in the tenant) and Locust's own request rate.

The dashboard is defined in code: `docs/dashboards/build_dashboard.py` writes `docs/dashboards/gov-demo.json`. `python3 docs/dashboards/build_dashboard.py --check` runs every tile query once against the tenant (one `dtctl` call at a time). `dtctl apply -f docs/dashboards/gov-demo.json` updates the dashboard in place, because the file carries its id. Not checked: how the tiles look in the browser, the layout and colours were built from the structure of an existing dashboard but not seen rendered.

## 10. Security

The legacy stub deliberately loads Log4j 2.14.1 (CVE-2021-44228), confirmed loaded at runtime. Whether the tenant flags it as a vulnerability is not confirmed: a DQL search of security events found nothing, which may be the wrong field names or runtime vulnerability analytics not being active under `applicationMonitoring`. Check Security, Vulnerabilities for `legacy-stub` in the UI. The stack must stay off the internet either way.
