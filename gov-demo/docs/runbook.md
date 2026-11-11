# Runbook: demo script

How to run the Carer Support Portal demo and what to show in Dynatrace for each scenario. Everything here was run against the lab cluster. Where something was not verified, it says so.

Fictional agency, fictional policy, synthetic data. Lab use only.

## Before you start

1. Cluster healthy: `kubectl get pods -n gov-demo` (all Running) and `kubectl get dynakube -n dynatrace` (Running).
2. Port-forwards (they die on a reboot): `kubectl port-forward -n gov-demo svc/web 8080:8080` and `kubectl port-forward -n gov-demo svc/locust 8089:8089`.
3. Pick the starting point: `make scenario NAME=baseline` (steady load, prompts are recorded and masked so the AI Observability Prompts view fills). `make scenario NAME=prompts_off` stops the recording.
4. Portal: http://localhost:8080. Sign in with any pair from `gov-demo/db/out/credentials.csv` (columns `citizen_id,passcode`, for example citizen 1). Avoid ids divisible by 20, they are non-residents and always ineligible. After sign in you land on the DynaGov home page (your services and inbox); open the Carer Support tile to start a claim. The assistant is a collapsed bar at the bottom right: click it to open the chat.
5. Locust: http://localhost:8089 shows the standing load.
6. Dashboard: open "Carer Support Portal demo" (https://imb05402.apps.dynatrace.com/ui/apps/dynatrace.dashboards/dashboard/fff6ca52-9dac-495c-91db-2f02b18cc977) and set the timeframe to the last 2 hours. It is the one screen for the whole story, see below.
7. Timing: data reaches the tenant 2 to 4 minutes after the action (logs a little later than spans). Open the views first, then act, then wait.
8. If you query with `dtctl`, run one call at a time.

State you should know about: toggles live in memory. Restarting a pod returns that service to its defaults. `make scenario NAME=reset` also stops the load, so afterwards run `baseline`.

## Cheat sheet

| Scenario | Command | Do | Show | Wait |
|---|---|---|---|---|
| baseline | `make scenario NAME=baseline` | Run one claim | Trace across all services, business events, AI app | 3 min |
| baseline (prompts) | `make scenario NAME=baseline` | Click the chat chips | AI Observability, Prompts | 3 min |
| bad_release | `make scenario NAME=bad_release` | Run claims as a citizen aged 45 to 54 | Deployment event, slower and failing eligibility | 2 min |
| monday_peak | `make scenario NAME=monday_peak` | Watch Locust ramp to 60 users | Slow legacy tier, queue growth, failed payments, problems | 5 min |
| upload_dropoff | `make scenario NAME=upload_dropoff` then `make browser-load PROFILE=abandoner SESSIONS=6` | Run completers and abandoners | RUM funnel, drop-off at upload | 3 min |
| ai_injection | `make scenario NAME=ai_injection` | Click "Prompt injection" | Leak of another citizen's data | 3 min |
| ai_pii | `make scenario NAME=ai_pii` | Open the Assistant, click "Message with a TFN", sign in | TFN in prompts and TFN and Medicare in logs | 4 min |
| ai_cost_spike | `make scenario NAME=ai_cost_spike` | Click "Long answer" | Token and cost jump | 3 min |
| ai_hallucination | `make scenario NAME=ai_hallucination` | Click "Check my eligibility" | Wrong amount and an invented clause | 3 min |
| provider_outage | `make scenario NAME=provider_outage` | Send a few chat prompts | 503 errors, error rate | 3 min |
| reset | `make scenario NAME=reset` | Nothing | Back to normal, no load | none |

`scenarios/verify.sh` checks that every scenario changes behaviour within one request.

## The dashboard

Open it first and leave it on screen. What moves for each scenario (based on the queries behind the tiles, not yet watched live in the browser):

| Scenario | Tiles that move |
|---|---|
| baseline | Journey by step, claims over time, tokens by type, chat latency, RUM funnel, web vitals (LCP, CLS, TTFB), journey completion rate |
| bad_release | Deployment events (new row), server response time p95 for claims-api, problems table |
| monday_peak | Payments failed, claims over time (failed line), queue wait (average and p95), server response time p95 for the legacy stub, problems table |
| upload_dropoff | RUM funnel (upload, review and status fall away), journey abandonment rate up, furthest step reached (a bar at 5 upload) |
| ai_injection, ai_pii | Prompts blocked (stays flat when guardrails are off), guardrail outcome per chat |
| ai_cost_spike | Tokens used and tokens by type |
| ai_hallucination | Answer groundedness (pass rate falls, failed count rises) |
| provider_outage | Chat errors by type, chat latency |

The web tiles (vitals, completion, abandonment, furthest step) cover browser sessions only, so they fill from `make browser-load` and your own clicks, not from Locust. Run `make browser-load PROFILE=completer SESSIONS=6` and `PROFILE=abandoner SESSIONS=6` before the demo so they have data.

## SLOs

Seven SLOs ("Carer portal: ...", 2 hour window) show the damage as budget burn. `monday_peak` burns eligibility latency (it falls to about 4 percent in the worst five minute buckets) and payment completion, `bad_release` burns eligibility latency, `provider_outage` burns assistant availability, `ai_hallucination` burns assistant answers grounded. The submission SLOs and assistant latency are green controls. Open them in the Service-Level Objectives app, or evaluate from the shell: `dtctl get slos` then `dtctl exec slo <id>`. The 2 hour window means a scenario's damage stays visible for a while after it ends, so for a clean start run `baseline` and allow time, or start the demo with the red ones as the "yesterday's incident" view.

## Suggested ten minute story

1. baseline: one claim, one trace (2 minutes).
2. bad_release: the deployment event and the damage it causes (2 minutes).
3. monday_peak: the legacy tier saturates and the queue grows (3 minutes).
4. AI: baseline (prompts), then ai_injection and ai_pii (3 minutes).
5. baseline to finish.

Start the slow-to-appear scenarios early and talk while the data arrives.

## baseline: one claim, one trace

Run: `make scenario NAME=baseline`. In the portal, sign in, open the Carer Support tile and complete a claim (payment type, details with low income and 35 hours, upload `db/out/sample-document.txt`, submit). Watch the status reach "paid".

Show:
- Distributed Traces, search for the `POST /api/claims/{claim_id}/submit` trace. One trace crosses `web` (Node, OneAgent), `claims-api` and its database calls (OpenTelemetry), the payment queue handover, `payment-worker` (OpenTelemetry) and the Java legacy stub (OneAgent). The queue row carries the W3C trace context, so the worker continues the same trace.
- Services, open `web`, Map tab: Government Claim Process (RUM) to `web` to `claims-api`, `llm-gateway`, the `govdemo` database, `LegacyController`, and `payment-worker` with `payment_queue`.
- Business events (see queries below): draft, eligibility, document, submitted, payment posted, with amounts and queue wait.

Say: Dynatrace's agent covers Node and Java, OpenTelemetry covers the Python services and the queue, and they join in one trace.

Queries (Notebook):
```
fetch bizevents | filter event.provider == "dcs.carer-portal" | summarize n = count(), by: {event.type}
```
Abandonment (drafts that never reached submit):
```
fetch bizevents, from: now()-30m
| filter event.provider == "dcs.carer-portal" and in(event.type, "claim.draft_created", "claim.submitted")
| summarize drafts = countIf(event.type == "claim.draft_created"), submitted = countIf(event.type == "claim.submitted"), by: {claim_id}
| filter submitted == 0
```

Caveats: the `web` spans are timestamped about 120 ms later than the claims-api spans below them (cause not found). OneAgent spans arrive before the OpenTelemetry spans, so a trace looks incomplete for the first minutes. The tenant has a second, unused RUM application called "Government Claims Process".

## Prompts: AI Observability

Run: `make scenario NAME=baseline`. In the portal, open the Assistant bar at the bottom right, then click "Check my eligibility", then "30 hours a week", then "Low income". The chat works by clicking: after each reply the assistant offers the next options.

Show, in AI Observability:
- Explorer: `claims-api` as the AI app, the `claims-assistant` agent, the model `gpt-4o-mini`, tokens and cost (cost is calculated for the mock model name).
- Prompts: the whole conversation including the tool call to `check_eligibility` and its result.
- Guardrails: the guardrail activation count per app.
- Conversation id: every span of one chat shares `gen_ai.conversation.id`.

```
fetch spans, from: now()-30m
| filter gen_ai.conversation.id == "<id from a span>"
| sort start_time asc
| fields start_time, service.name, span.name, span.kind
```

Say: the model is a mock (spans carry `demo.mock=true`, provider `azure.ai.openai`, model `gpt-4o-mini`). The telemetry shape is what a real client would emit.

Caveats: the "Overall guardrail activation" card and the activation-by-type chart stay at 0, they appear to read Bedrock-style attributes. The "Average request duration" tile showed 555.95 microseconds while the real value is 0.56 seconds (the metric value is correct, cause of the tile not found). Not checked: the Agents topology (Preview) page.

## bad_release: deployment event and a bad eligibility engine

Run: `make scenario NAME=bad_release`. Eligibility becomes 0.4 to 1.2 s slower (a rate schedule read on every check) and fails with a server error for citizens aged 45 to 54, because release 2's schedule has no band for them. Find a citizen in that band by date of birth (the verify script does this) and run a claim. The agentic version of this story, where an agent investigates and fixes it, is in `docs/agentic-demo.md`.

Show:
- A `CUSTOM_DEPLOYMENT` event named "eligibility-engine release v2" on the claims-api service, 1 to 2 minutes after the switch. It comes from a log line turned into an event by OpenPipeline, no token involved.
- Service claims-api: slower eligibility, errors.

```
fetch events, from: now()-30m | filter event.type == "CUSTOM_DEPLOYMENT"
```

Caveat: the deployment event was verified. Whether Davis opens a problem for this scenario and links it to the event was not checked. Switching back (`baseline`) logs a second event.

## monday_peak: legacy tier saturates

Run: `make scenario NAME=monday_peak`. The legacy stub is slow (2 to 5 s per call), the payment worker has one thread, and Locust ramps to 60 users over 3 minutes.

Observed on the lab cluster: eligibility averages climb from about 130 ms to several seconds, the p95 reaches 4 to 12 s, failures settle around 1 to 5 percent, the payment queue grows from 0 to over 30 pending while almost nothing completes, and some payments fail after retries (the `claim.payment_failed` event, error "timed out"). The VM stays at about 26 percent CPU, the bottleneck is the stub by design. The stub does not restart: its health and control API run on a separate port.

Show:
- Services map for `web`: response time problems on `LegacyController` and downstream services.
- Distributed Traces: slow eligibility traces dominated by the legacy call.
- Business events: `claim.payment_failed` and `claim.payment_posted` with `queue_wait_ms` rising.
- Queue depth (not in the tenant, read the table):
```
kubectl exec -n gov-demo deploy/postgres -c postgres -- sh -c "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \"select status, count(*) from payment_queue group by 1\""
```
```
fetch bizevents, from: now()-4h | filter event.type == "claim.payment_failed" | summarize n = count(), by: {error}
```

Finish with `make scenario NAME=baseline`. This matters: the load profile returns to baseline by itself after the peak, but the scenario toggles stay set, so the stub stays slow and the worker stays on one thread, and your Davis problems and SLOs keep burning, until you run `baseline`. It works even while the stub is saturated and takes a couple of seconds. The queue then drains (the worker returns to two threads).

Davis: the tenant's detection is deliberately not tuned and the SLOs are the burn story. Davis does raise problems for the peak, but late (about 10 minutes in the last run) and as separate problems: `web` ends at "Requests to unmonitored hosts" (it sees the OpenTelemetry-only `claims-api` as an unmonitored host), the `claims-api` problems stand alone, and the legacy stub itself may not get one. If asked, call it a mixed estate effect, do not promise "Davis points at the legacy tier", and see `dynatrace-config.md` section 8 for the detail and the two options if you want to improve it. The load profile returns to baseline by itself after the 10 minute hold and ramp down.

## upload_dropoff: RUM funnel

Run: `make scenario NAME=upload_dropoff` (uploads take 3 to 8 s), then real browser sessions: `make browser-load PROFILE=completer SESSIONS=6` and `make browser-load PROFILE=abandoner SESSIONS=6`. Abandoners reach the upload step and leave.

Show, in the RUM application (Government Claim Process): views per step and the drop-off. Verified numbers from one run (12 sessions ingested): login, payment-type, details and eligibility 12, upload 8, review 5, status 5.

```
fetch user.events, from: now()-30m
| filter dt.rum.application.entity == "APPLICATION-EA7C4B59F27D43EB" and characteristics.has_view_summary == true
| summarize sessions = countDistinct(dt.rum.session.id), by: {view.detected_name}
| sort sessions desc
```

Notes: each step is its own URL path (`/upload`, `/review`, ...), which is what makes the funnel possible (hash routes gave a single view). RUM's automatic actions also name every transition ("click on button on /upload"). The classic custom actions `step_*` are not stored by this tenant's RUM. Not verified: Session Replay (it may need enabling for the RUM application). The browser trace continues through `web` into the OpenTelemetry `claims-api`.

## ai_injection: guardrails off, data leaks

Run: `make scenario NAME=ai_injection`. In the chat click "Prompt injection". With guardrails off the assistant answers with another citizen's synthetic claim summary including a TFN. With guardrails on (baseline) the same prompt is blocked and flagged.

Show:
- Prompts view (recorded by default): the injection prompt and the leaked answer. Compare with the blocked answer from baseline.
- No filter annotations are returned when guardrails are off, so those requests stop counting as guardrail enabled.

```
fetch spans, from: now()-30m
| filter service.name == "claims-api" and startsWith(toString(span.name), "chat ")
| summarize chats = count(), blocked = countIf(matchesPhrase(toString(gen_ai.response.finish_reasons), "content_filter")), jailbreak = countIf(matchesPhrase(toString(gen_ai.prompt.prompt_filter_results), "\"jailbreak\": {\"filtered\": true"))
```

Say: the detection is the gateway's guardrail (a list of known injection phrases). Dynatrace does not detect injection itself, it shows the outcome the provider reports and, with prompt recording, the text. A reworded attack would slip past this mock.

## ai_pii: identifiers in prompts and logs

Run: `make scenario NAME=ai_pii` (prompts are already recorded by default, this adds identifiers to the logs and switches Locust to the assistant profile). Open the Assistant and click "Message with a TFN". Sign in again (the sign in log line carries the identifiers). The assistant answers politely and tells the user not to share a TFN, without echoing it.

Show:
- Prompts view and the chat span: the TFN `123456782` in `gen_ai.input.messages`.
- Logs: claims-api sign in and eligibility log lines with `tfn`, `medicare_number` and `irn` in clear.

```
fetch logs, from: now()-30m
| filter k8s.workload.name == "claims-api" and contains(content, "\"tfn\"") and contains(content, "medicare_number")
| fields timestamp, content
```
```
fetch spans, from: now()-30m
| filter service.name == "claims-api" and startsWith(toString(span.name), "chat ") and matchesPhrase(toString(gen_ai.input.messages), "123456782")
| summarize n = count()
```

Masking: with the OpenPipeline rule in `dynatrace-config.md` (section 6) the log lines arrive as `"tfn": "[masked]"` and `"medicare_number": "[masked]"`. Compare with the pod log (`kubectl logs -n gov-demo deploy/claims-api -c claims-api --since=1m | grep '"tfn"'`) where the digits are still in clear: the app writes them, Dynatrace masks them at ingest. Prompts are masked the same way: in the Prompts view and on the chat span the TFN reads `My TFN is [masked]`. Lines and spans ingested before the rules existed stay as they were, so use a time window after the rules when you show it. After the demo run `make scenario NAME=baseline`.

## ai_cost_spike: verbose answers

Run: `make scenario NAME=ai_cost_spike`, click "Long answer" or any prompt a few times. Answers get long, output tokens jump.

Show: AI Observability, token usage and cost over time; the metric by token type:
```
timeseries tokens = sum(gen_ai.client.token.usage), by: {gen_ai.token.type}, from: now()-30m
```

## ai_hallucination: wrong answers

Run: `make scenario NAME=ai_hallucination`, click "Check my eligibility" (guided: pick hours and income) or "Quick check". The amount is 37 percent too high and the answer adds a non-existent clause (section 14B(2) of the Carer Support Act 2031). Guardrails are off here, because with guardrails on the grounding check blocks the wrong amount.

Show:
- Prompts view: the answer next to the rules engine result in the tool call (the tool result holds the correct amount). Compare with `baseline`.
- Evaluation results: after each answer built on the eligibility tool, claims-api checks it with a deterministic rule and a `gen_ai.evaluation.result` event lands in the tenant with label `fail` and the explanation ("quotes $356.20 but the rules engine returned $260.00; cites a policy section that does not exist"). It links to the chat by `gen_ai.conversation.id` and to the trace by trace id.
- The dashboard: "Failed groundedness evaluations" and the evaluation results over time, and the SLO "Carer portal: assistant answers grounded" burning (86 percent in the test run against a 95 percent target).

```
fetch bizevents, from: now()-30m
| filter event.type == "gen_ai.evaluation.result"
| summarize results = count(), by: {`gen_ai.evaluation.score.label`}
```
```
fetch bizevents, from: now()-30m
| filter event.type == "gen_ai.evaluation.result" and `gen_ai.evaluation.score.label` == "fail"
| fields timestamp, `gen_ai.evaluation.explanation`, `gen_ai.conversation.id`, trace_id
```

Say plainly: the evaluation is synthetic (`demo_synthetic = true`), a deterministic rule stands in for a judge model, because a mock gateway cannot judge itself. In production this is where an LLM judge or the dt-evals toolkit would sit. Dynatrace itself does not detect a hallucination, it stores the evaluation results you give it.

Not verified: whether the AI Observability app has a view for these evaluation results. The DQL and the dashboard show them.

## provider_outage: model provider errors

Run: `make scenario NAME=provider_outage`. About 30 percent of chat requests fail with 503. Send several prompts in the chat (the widget shows "The assistant is unavailable right now") or let Locust's assistant users run (`ai_pii` or `ai_injection` first switch Locust to assistant load).

Show: error rate on the `claims-api` AI app and the failed `chat` spans with `error.type` = 503.
```
fetch spans, from: now()-30m
| filter service.name == "claims-api" and startsWith(toString(span.name), "chat ")
| summarize chats = count(), failed = countIf(isNotNull(error.type)), by: {error.type}
```
Not checked in the UI: the Errors tab of AI Observability.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Portal shows "not signed in" or returns to sign in | claims-api restarted, sessions are in memory. Sign in again |
| A scenario seems to have vanished | A pod restarted and its toggles reset. Run the scenario again |
| Prompts view stops filling | Recording was turned off with `prompts_off`. Run `make scenario NAME=baseline` |
| No data in the tenant | Wait 2 to 4 minutes. Logs lag spans. Then check the DynaKube is Running and the pods are injected |
| `dtctl` says the token refresh failed | Run `dtctl auth login`. Never run `dtctl` calls in parallel |
| Port 8080 or 8089 refused | The port-forward died, start it again |
| Locust shows 0 users | The last scenario was `reset` (no load). Run `baseline` |
| No claims, business events or journey data, but spans and chat traffic flow | Locust was left running assistant users only (fixed: profiles now name their user classes). Check `POST /api/claims` against `POST /api/assistant` in the Locust stats. A restart of the Locust pod, `kubectl rollout restart -n gov-demo deploy/locust`, always gives a fresh mix |
| Data in the cluster's Dynatrace but nothing from `make up` | `make up` is the Docker Compose stack. It has no OneAgent and no OTLP export, so it never sends anything to Dynatrace. The tenant is fed by the Kubernetes deployment (`make deploy`) |
| Disk worries | `make disk` reports usage. Demo rows older than 6 hours are deleted every 15 minutes. `make prune` reclaims build cache |

## Known gaps

- The duration tile in AI Observability misreads the unit (the metric value is correct).
- Guardrail activation card and by-type chart stay at 0.
- Vulnerability detection of the old log4j needs the two settings in `dynatrace-config.md` section 10. It works once they are applied (confirmed 2026-11-11), but the first findings take a few minutes after `legacy-stub` restarts. Check Security, Vulnerabilities, filtered to `gov-demo`.
- Masking covers the labelled TFN and Medicare forms only. The SLO window is 2 hours, so burn lingers after a scenario.
- Davis problems appear during the peak, late and fragmented, with no root cause on the stub. Decided not to tune, the SLOs carry the burn story.
- Session Replay not verified.
- The hallucination evaluation is a synthetic rule, not a judge model, and its display in AI Observability is not verified.
