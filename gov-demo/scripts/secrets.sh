#!/usr/bin/env bash
# Usage: scripts/secrets.sh init|check
# Manages secrets/*.env from secrets/*.env.example. Prints key names only, never values.
set -euo pipefail
cd "$(dirname "$0")/../secrets"

keys() { grep -E '^[A-Z][A-Z0-9_]*=' "$1" | cut -d= -f1; }
value() { grep -E "^$2=" "$1" | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//' | tr -d '[:space:]'; }

case "${1:-}" in
  init)
    for ex in *.env.example; do
      [ -e "$ex" ] || continue
      real="${ex%.example}"
      if [ -e "$real" ]; then echo "exists:  secrets/$real"; continue; fi
      cp "$ex" "$real"; chmod 600 "$real"
      echo "created: secrets/$real  (edit it and fill in the values)"
    done
    ;;
  check)
    rc=0
    for ex in *.env.example; do
      [ -e "$ex" ] || continue
      real="${ex%.example}"
      if [ ! -e "$real" ]; then echo "MISSING file: secrets/$real (run make secrets-init)"; rc=1; continue; fi
      perm=$(stat -f '%Lp' "$real" 2>/dev/null || stat -c '%a' "$real")
      [ "$perm" = "600" ] || { echo "WARN secrets/$real permissions are $perm, expected 600"; }
      for k in $(keys "$ex"); do
        v=$(value "$real" "$k")
        case "$k" in DT_RUM_SNIPPET_URL) continue ;; esac   # optional
        if [ -z "$v" ] || [[ "$v" == *"<"*">"* ]]; then echo "EMPTY   $real: $k"; rc=1; else echo "ok      $real: $k"; fi
      done
    done
    exit $rc
    ;;
  *) echo "usage: $0 init|check"; exit 2 ;;
esac
