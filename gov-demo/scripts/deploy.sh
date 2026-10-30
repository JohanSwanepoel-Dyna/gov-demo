#!/usr/bin/env bash
# Deploy the Carer Support Portal demo to the current kubectl context.
#
#   scripts/deploy.sh [--yes] [--dry-run] [--registry REG] [--tag TAG] [--platforms LIST]
#   make deploy [REGISTRY=ghcr.io/you/gov-demo] [TAG=v1] [YES=yes] [DRYRUN=yes]
#
# Local cluster (Rancher Desktop, Docker Desktop, OrbStack, Colima): builds the images with your Docker, the cluster
# uses them directly. Any other cluster: pass --registry, the images are built for amd64 and arm64 and pushed (run
# `docker login` first). --dry-run only reads from the cluster and prepares local files, it changes nothing else.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=gov-demo
REGISTRY="${REGISTRY:-}"
TAG="${TAG:-}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
YES="${YES:-no}"
DRY=no
IMAGES="web:services/web claims-api:services/claims-api llm-gateway:services/llm-gateway payment-worker:services/payment-worker legacy-stub:services/legacy-stub locust:load/locust seed:db"
DEPLOYMENTS="postgres legacy-stub claims-api llm-gateway payment-worker web locust"

while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=yes ;;
    --dry-run) DRY=yes ;;
    --registry) REGISTRY="$2"; shift ;;
    --tag) TAG="$2"; shift ;;
    --platforms) PLATFORMS="$2"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
run() { if [ "$DRY" = yes ]; then printf '   [dry run] %s\n' "$*"; else "$@"; fi; }
fail() { echo "error: $*" >&2; exit 1; }

step "Preflight"
for tool in kubectl docker python3; do command -v "$tool" >/dev/null || fail "missing tool: $tool"; done
CTX=$(kubectl config current-context 2>/dev/null) || fail "no kubectl context is set"
note "kubectl context: $CTX"
kubectl version --request-timeout=10s >/dev/null 2>&1 || fail "cannot reach the cluster for context $CTX"
ARCHS=$(kubectl get nodes -o jsonpath='{range .items[*]}{.status.nodeInfo.architecture}{"\n"}{end}' | sort -u | tr '\n' ' ')
note "node architecture: ${ARCHS:-unknown}"

if [ -z "$REGISTRY" ]; then
  case "$CTX" in
    rancher-desktop|docker-desktop|orbstack|colima) note "local cluster: images are built with your Docker and used directly" ;;
    *) fail "context '$CTX' does not look like a local cluster that shares your Docker images. Pass --registry (for example ghcr.io/you/gov-demo)." ;;
  esac
else
  TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo dev)}"
  docker buildx version >/dev/null 2>&1 || fail "docker buildx is needed to build and push multi-architecture images"
  note "registry mode: $REGISTRY/<service>:$TAG for $PLATFORMS"
fi

if kubectl get crd dynakubes.dynatrace.com >/dev/null 2>&1; then
  note "Dynatrace Operator found. DynaKubes:"
  kubectl get dynakube -A -o jsonpath='{range .items[*]}     {.metadata.namespace}/{.metadata.name} phase {.status.phase}{"\n"}{end}' 2>/dev/null || true
  kubectl get dynakube -A -o jsonpath='{range .items[*]}{.spec.oneAgent}{"\n"}{end}' 2>/dev/null | grep -q "applicationMonitoring\|cloudNativeFullStack" \
    || note "warning: no DynaKube with applicationMonitoring or cloudNativeFullStack, the pods will not be injected"
else
  note "warning: the Dynatrace Operator is not installed on this cluster. The demo runs, but nothing reaches Dynatrace."
  note "         See docs/deploy.md for the Operator and DynaKube."
fi

if [ "$YES" != yes ] && [ "$DRY" != yes ]; then
  printf '\nDeploy to context "%s" (namespace %s)? [y/N] ' "$CTX" "$NS"
  read -r answer
  [ "$answer" = y ] || [ "$answer" = Y ] || { echo "cancelled"; exit 1; }
fi

step "Local files"
if [ ! -f .env ]; then
  pw() { python3 -c 'import secrets; print(secrets.token_hex(16))'; }
  sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(pw)/" -e "s/^CONTROL_TOKEN=.*/CONTROL_TOKEN=$(pw)/" .env.example > .env
  chmod 600 .env
  note "created .env with generated passwords (gitignored)"
else
  note ".env exists, left as it is"
fi
if [ ! -f db/out/credentials.csv ]; then
  mkdir -p db/out
  python3 db/seed.py --csv-only --out db/out/credentials.csv >/dev/null
  note "generated db/out/credentials.csv (citizen ids and passcodes for Locust, Playwright and you)"
else
  note "db/out/credentials.csv exists, left as it is"
fi

step "Images"
for item in $IMAGES; do
  name=${item%%:*}; dir=${item#*:}
  if [ "$DRY" = yes ]; then
    if [ -z "$REGISTRY" ]; then note "[dry run] would build gov-demo/$name:dev"; else note "[dry run] would build and push $REGISTRY/$name:$TAG"; fi
  elif [ -z "$REGISTRY" ]; then
    docker build -q -t "gov-demo/$name:dev" "$dir" >/dev/null
    note "built gov-demo/$name:dev"
  else
    docker buildx build --platform "$PLATFORMS" -t "$REGISTRY/$name:$TAG" --push "$dir"
  fi
done

step "Namespace and secrets"
if [ "$DRY" = yes ]; then
  note "[dry run] would create namespace $NS and the secrets gov-demo-env (from .env) and gov-demo-credentials (from the CSV)"
else
  kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$NS" create secret generic gov-demo-env --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$NS" create secret generic gov-demo-credentials --from-file=credentials.csv=db/out/credentials.csv --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  note "namespace and secrets are in place (secret values are never written to the manifests)"
fi

step "Apply"
MANIFESTS=k8s
if [ -n "$REGISTRY" ]; then
  MANIFESTS=$(mktemp -d)
  cp -R k8s/. "$MANIFESTS"
  { echo "images:"; for item in $IMAGES; do n=${item%%:*}; printf '  - name: gov-demo/%s\n    newName: %s/%s\n    newTag: "%s"\n' "$n" "$REGISTRY" "$n" "$TAG"; done; } >> "$MANIFESTS/kustomization.yaml"
  # A Job spec cannot be edited in place. The seed is idempotent, so run it again with the new image.
  run kubectl delete job seed -n "$NS" --ignore-not-found
fi
run kubectl apply -k "$MANIFESTS"

if [ "$DRY" = yes ]; then
  step "Dry run finished: nothing was built, pushed or applied"
  exit 0
fi

step "Waiting for the stack"
kubectl wait --for=condition=complete job/seed -n "$NS" --timeout=300s >/dev/null && note "database seeded (500 citizens)"
for d in $DEPLOYMENTS; do
  kubectl rollout status "deploy/$d" -n "$NS" --timeout=300s >/dev/null && note "$d is ready"
done

step "Done"
kubectl get pods -n "$NS"
cat <<EOF

Open the portal:   kubectl port-forward -n $NS svc/web 8080:8080      then http://localhost:8080
Locust (load):     kubectl port-forward -n $NS svc/locust 8089:8089   then http://localhost:8089
Sign in with any pair from db/out/credentials.csv (citizen_id,passcode). Avoid ids divisible by 20.
Scenarios:         make scenario    (lists them), make scenario NAME=monday_peak
Status and tidy:   make status, make undeploy
Dynatrace side:    docs/dynatrace-config.md (OpenPipeline, SLOs, dashboard)
EOF
