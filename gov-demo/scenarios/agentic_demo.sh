#!/usr/bin/env bash
# Arm, check or reset the agentic development demo (docs/agentic-demo.md).
#
#   scenarios/agentic_demo.sh arm      restore the committed eligibility engine, rebuild claims-api, switch to release v2
#   scenarios/agentic_demo.sh redeploy rebuild claims-api from the working tree (the agent's fix) and switch back to release v2
#   scenarios/agentic_demo.sh status   show whether the engine file is the committed one and which release is active
#   scenarios/agentic_demo.sh reset    discard an agent's fix, rebuild claims-api, go back to release v1 and baseline load
#
# `arm` and `reset` run `git checkout` on services/claims-api/eligibility.py, so an uncommitted fix is discarded.
# They need the kubectl context for the cluster that runs the demo (Rancher Desktop here).
set -euo pipefail
cd "$(dirname "$0")/.."
NS=gov-demo
FILE=services/claims-api/eligibility.py
YES="${YES:-no}"

step() { printf '\n== %s\n' "$*"; }
release() {
  kubectl exec -n "$NS" deploy/claims-api -c claims-api -- python -c \
    "import os,json,urllib.request as u;r=u.Request('http://localhost:8000/control/toggles',headers={'X-Demo-Control':os.environ['CONTROL_TOKEN']});print(json.load(u.urlopen(r))['eligibility_release'])" 2>/dev/null || echo unknown
}
restore_engine() {
  if ! git diff --quiet -- "$FILE"; then
    echo "This discards your uncommitted changes to $FILE:"; git diff --stat -- "$FILE"
    if [ "$YES" != yes ]; then printf 'Continue? [y/N] '; read -r a; [ "$a" = y ] || [ "$a" = Y ] || { echo cancelled; exit 1; }; fi
  fi
  git checkout -- "$FILE"
}
rebuild() {
  step "Rebuild and restart claims-api"
  docker build -q -t gov-demo/claims-api:dev services/claims-api >/dev/null
  kubectl -n "$NS" rollout restart deploy/claims-api >/dev/null
  kubectl -n "$NS" rollout status deploy/claims-api --timeout=180s | tail -1
}

case "${1:-}" in
  arm)
    echo "kubectl context: $(kubectl config current-context)"
    restore_engine; rebuild
    step "Switch to release v2 with steady load"
    make -s scenario NAME=bad_release
    echo; echo "Armed. The deployment event reaches Dynatrace in 1 to 2 minutes, errors and slow checks in 2 to 4."
    ;;
  redeploy)
    echo "kubectl context: $(kubectl config current-context)"
    rebuild
    step "Release v2 again, with the code in the working tree"
    make -s scenario NAME=bad_release
    echo; echo "Redeployed. Compare errors and latency after this point with the minutes before it."
    ;;
  status)
    echo "release toggle: $(release)"
    if git diff --quiet -- "$FILE"; then echo "$FILE: as committed (the defect is present)"; else echo "$FILE: changed from the committed version:"; git diff --stat -- "$FILE"; fi
    ;;
  reset)
    echo "kubectl context: $(kubectl config current-context)"
    restore_engine; rebuild
    step "Back to release v1 and baseline load"
    make -s scenario NAME=baseline
    ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
