# Deploy to your cluster

One command deploys the whole demo to the cluster your `kubectl` currently points at. Fictional agency, fictional policy, synthetic data. Lab use only, never expose it to the internet (the legacy stub deliberately loads an old Log4j).

## What you need

| Need | Notes |
|---|---|
| `kubectl` with a context for the target cluster | `kubectl config current-context` shows which one will be used |
| Docker | Builds the images. For a remote cluster you also need `docker buildx` and a registry you can push to |
| `python3` | Used by the script to generate passwords and the credentials file |
| Dynatrace Operator and a DynaKube with `applicationMonitoring` | Optional for the demo to run, required for anything to reach Dynatrace. See below |

## Quick start (local cluster)

For Rancher Desktop, Docker Desktop, OrbStack or Colima, where the cluster uses your own Docker images:

```
make deploy DRYRUN=yes     # optional: preflight and plan, changes nothing on the cluster
make deploy                # asks to confirm the context, then deploys
```

What it does, in order:
1. Preflight: shows the context and node architecture, checks the Dynatrace Operator and DynaKube, and asks you to confirm the context (skip with `YES=yes`).
2. Creates `.env` with generated random passwords if you have none, and `db/out/credentials.csv` (citizen ids and passcodes, the same every time) if you have none. Both are gitignored.
3. Builds the seven images (`gov-demo/<service>:dev`).
4. Creates the namespace `gov-demo` and two Secrets from those files. Secret values never go into manifests.
5. `kubectl apply -k k8s/`, then waits for the seed job and every deployment.
6. Prints how to open the portal.

It is safe to run again: unchanged objects stay unchanged and nothing restarts. To pick up a code change, rebuild and restart that service: `make images` then `kubectl rollout restart -n gov-demo deploy/<service>`.

## Any other cluster (registry)

The cluster cannot see your local Docker images, so the script builds for amd64 and arm64 and pushes them:

```
docker login ghcr.io
make deploy REGISTRY=ghcr.io/you/gov-demo TAG=v1
```

`TAG` defaults to the short git commit. The script rewrites every image reference at apply time (the manifests themselves keep `gov-demo/<service>:dev`) and re-runs the seed job so it uses the new image. Make the registry packages pullable by the cluster, or add an image pull secret to the namespace.

Not verified in this repository: an actual push to a registry and a deployment to a non-local cluster. What was verified is the dry run, and that the generated override rewrites all seven image names while leaving Postgres alone.

The multi-architecture build runs the Java build under emulation on the other architecture, which is slow the first time.

## Open it

```
kubectl port-forward -n gov-demo svc/web 8080:8080       # http://localhost:8080
kubectl port-forward -n gov-demo svc/locust 8089:8089    # http://localhost:8089
```

Sign in with any pair from `db/out/credentials.csv` (citizen id, passcode). Avoid ids divisible by 20, they are non-residents and always ineligible. Then `make scenario` lists the scenarios and `make scenario NAME=baseline` starts the steady load. `make status` shows the pods and the DynaKube.

## Dynatrace side

The demo needs a tenant with the Dynatrace Operator and a DynaKube in the cluster:

- `applicationMonitoring` (injection into pods) and `telemetryIngest` with OTLP, see section 1 of `dynatrace-config.md`. Use `applicationMonitoring` on nodes without glibc (Rancher Desktop is Alpine).
- Namespaces are injected automatically when the DynaKube has no namespace selector.
- No API token is needed by the app.

Then, per tenant, with `dtctl` (one call at a time, these change tenant settings, read the files first):

1. OpenPipeline for business events, the deployment event and masking: `docs/openpipeline/*.yaml` and the routing steps in `dynatrace-config.md` sections 3 and 6.
2. SLOs: `dtctl create slo -f docs/slos/<name>.yaml`.
3. Dashboard: `python3 docs/dashboards/build_dashboard.py --check` then `dtctl apply -f docs/dashboards/gov-demo.json`.

Caveat for a different tenant: the dashboard generator and the OpenPipeline files contain tenant-specific ids (the five service entity ids, the RUM application id `APPLICATION-EA7C4B59F27D43EB`, the dashboard id and the pipeline object ids). Find your own with DQL (`fetch dt.entity.service`, `fetch dt.entity.application`) and update `build_dashboard.py` before applying, and drop the `DASHBOARD_ID` so a new dashboard is created.

## Tidy up

`make undeploy` deletes the namespace after asking. It does not remove images, local files, or anything in the Dynatrace tenant (pipelines, routing, SLOs, dashboard).

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `ImagePullBackOff` | Registry mode: the cluster cannot pull the images (visibility or pull secret). Local mode on a remote context: use `--registry` |
| Preflight says no local cluster | The context is not Rancher Desktop, Docker Desktop, OrbStack or Colima. Pass `REGISTRY=` |
| Seed job never completes | `kubectl logs -n gov-demo job/seed`, usually Postgres is not ready yet or the password changed after the volume was created |
| Pods are Running but nothing in Dynatrace | The namespace is not injected: no DynaKube, or it has a namespace selector that excludes `gov-demo`. Wait 2 to 4 minutes after the first traffic |
| Changed the password in `.env` and Postgres rejects it | The password is stored in the Postgres volume. Delete the namespace (this deletes the data) and deploy again |
| Port-forward refused | The port-forward died, start it again |
