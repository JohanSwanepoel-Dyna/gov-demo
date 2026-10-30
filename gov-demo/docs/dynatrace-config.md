# Tenant-side configuration

Items configured in the Dynatrace tenant, not built in the repo. This file grows in Phase 8.

## Business events from logs (OpenPipeline)

The apps log structured JSON. Lines that represent a business event carry a `business_event` field:

| business_event | Emitted by | Other fields |
|---|---|---|
| `claim.draft_created` | claims-api | claim_id, payment_type |
| `claim.eligibility_checked` | claims-api | claim_id, decision, duration_ms |
| `claim.document_uploaded` | claims-api | claim_id, size_bytes |
| `claim.submitted` | claims-api | claim_id, payment_type, reference |
| `claim.payment_posted` | payment-worker | claim_id, amount_cents, queue_wait_ms |
| `claim.payment_failed` | payment-worker | claim_id, error (final failure only) |

OneAgent log ingestion keeps the JSON in `content` and only lifts `trace_id` and `span_id` to attributes, so the pipeline first parses the JSON, then extracts one business event per type. No ingest token is needed.

1. Create the pipeline:
   `dtctl apply -f docs/openpipeline/gov-demo-logs-pipeline.yaml`
2. Add one entry to the logs routing table (Settings, OpenPipeline, Logs, Dynamic routing), after any broader rules:
   - Matcher: `matchesValue(k8s.namespace.name, "gov-demo") and (matchesPhrase(content, "business_event") or matchesPhrase(content, "deployment_event"))`
   - Pipeline: `gov-demo business events` (custom id `pipeline_gov_demo_bizevents`)
3. Check: `dtctl query 'fetch bizevents, from: now()-15m | filter event.provider == "dcs.carer-portal" | summarize count(), by: {event.type}'`

Abandonment is derived in DQL as `claim.draft_created` without a later `claim.submitted` for the same `claim_id`.

## Deployment event for the eligibility release toggle

When `eligibility_release` changes, claims-api logs a line with `deployment_event`, `deployment_name`, `release_version` and `previous_version`. The same pipeline parses it and a Davis event processor creates a `CUSTOM_DEPLOYMENT` event on the claims-api service. No token is needed. Verify with:
`dtctl query 'fetch events, from: now()-30m | filter event.type == "CUSTOM_DEPLOYMENT"'`
