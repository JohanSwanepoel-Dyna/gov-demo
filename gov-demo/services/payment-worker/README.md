# payment-worker

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | 8200 | Health and control port |
| `DATABASE_URL` | required | Postgres DSN |
| `POLL_INTERVAL_S` | 1 | Sleep between polls when the queue is empty |
| `WORKER_CONCURRENCY` | 2 | Initial concurrency (1 to 8). Adjustable at runtime through the toggle API |
| `PROCESSING_DELAY_MS` | 0 | Initial artificial delay per item (0 to 10000). Adjustable at runtime |
| `MAX_ATTEMPTS` | 3 | Attempts before a row is marked failed |
| `BACKOFF_BASE_S` | 2 | Retry delay is base times 2^(attempt-1) seconds |
| `LEGACY_URL` | http://legacy-stub:8300 | Legacy stub base URL |
| `LEGACY_TIMEOUT_S` | 15 | Legacy call timeout |
| `CONTROL_TOKEN` | none | Shared secret for the toggle API, sent as header `X-Demo-Control`. The API is disabled when unset |

## Toggle API

`GET` and `PUT /control/toggles` with header `X-Demo-Control`. Toggles: `concurrency` (1 to 8) and `processing_delay_ms` (0 to 10000). State is in memory and resets on restart.
