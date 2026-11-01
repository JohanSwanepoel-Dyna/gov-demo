# Government Demo App (Carer Support Portal)

Fictional "Department of Community Services" demo for Dynatrace. All policy, thresholds, amounts and citizen data are invented and synthetic. Lab use only: the legacy stub will carry a deliberately vulnerable library, so do not expose this stack to the internet.

## Quick start

```
cp .env.example .env
make up      # build and start everything, waits for healthy
make ps
make down
```

Credentials for load tools are written to `db/out/credentials.csv` by the seed step (`make seed` re-runs it).

## Browser load (Playwright)

Real Chrome sessions for the browser side of the demo: the RUM funnel, completion and abandonment, web vitals, and the "Web experience" part of the dashboard. Locust is protocol level and has no browser, so those tiles stay empty until you run this.

1. The portal must be reachable on `localhost:8080`. On Kubernetes: `kubectl port-forward -n gov-demo svc/web 8080:8080` (leave it running). Chrome must be installed.
2. Run one or more profiles from this folder:

```
make browser-load PROFILE=completer SESSIONS=8      # full journey to a paid claim
make browser-load PROFILE=abandoner SESSIONS=6      # leaves at the upload step
make browser-load PROFILE=assistant SESSIONS=3      # opens the chat and clicks two prompts
```

3. Wait 3 to 4 minutes, then open the dashboard "Carer Support Portal demo" with the timeframe set to the last 30 minutes. Completion and abandonment need both completers and abandoners, run both.

Options such as `CONCURRENCY=`, `BASE_URL=` (another port or machine) and `--headed` to watch the browser are in `load/browser/README.md`. The scenario script, the dashboard and the SLOs are covered in `docs/runbook.md`.

## Deploy to Kubernetes

`make deploy` deploys the whole demo to the cluster your `kubectl` points at (preflight, local files, images, namespace and secrets, apply, wait). Local clusters such as Rancher Desktop use your own Docker images, any other cluster uses `make deploy REGISTRY=ghcr.io/you/gov-demo`. `make deploy DRYRUN=yes` shows the plan first, `make status` and `make undeploy` finish the job. Details, the Dynatrace side and troubleshooting are in `docs/deploy.md`.

Ports: web 8080, claims-api 8000, llm-gateway 8100, payment-worker 8200, legacy-stub 8300, locust 8089.

`make up` is the Docker Compose stack and it is local only: it has no OneAgent and no telemetry export, so it never sends anything to Dynatrace. Data in Dynatrace comes from the Kubernetes deployment (`make deploy`, see below). Both use port 8080 on your machine, so stop one of them (`make down` for Compose) or use a different port for the Kubernetes port-forward.

## Environment variables (root `.env`)

| Variable | Purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Postgres credentials and database name |
| `CONTROL_TOKEN` | Shared secret for `X-Demo-Control` on toggle APIs |

Per-service variables are in each service README.

## Scenarios

```
make scenario                    # list scenarios
make scenario NAME=monday_peak   # apply one (resets everything else to defaults first)
make scenario NAME=reset         # back to the baseline
scenarios/verify.sh              # checks every scenario changes behaviour within one request
```

The runner reaches the services through temporary `kubectl port-forward` sessions (add `TARGET=compose` for the Compose stack) and reads `CONTROL_TOKEN` from `.env`. Toggle state is in memory, so a pod restart returns that service to its defaults.

## Disk

Locust is always on, so the demo creates data and logs continuously. What keeps it bounded:

| What grows | Safeguard |
|---|---|
| Postgres rows (claims, documents, queue, payments) | A retention job deletes demo data older than `RETENTION_HOURS` (default 6) every 15 minutes: a CronJob on k3s, a looping `retention` service in Compose. Seeded citizens are kept. Uploads are capped at 1 MB |
| Container logs | Compose rotates logs (10 MB, 3 files per service). Services no longer log every request, only errors and slow calls unless `ACCESS_LOG=on`. On k3s with Docker as the runtime, Docker's own log driver has no size limit by default, so check `make disk` after long runs |
| Images and build cache | `make prune` reclaims build cache older than a day and dangling images (dangling images are machine wide) |

`make disk` shows Docker usage, the filesystem behind Docker, the database size and the largest container logs.
