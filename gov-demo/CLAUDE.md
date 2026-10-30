# CLAUDE.md

Spec: ../gov-demo-spec.md. Progress: ../PROGRESS.md.

## Instructions for Claude Code

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

## Repo layout

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

