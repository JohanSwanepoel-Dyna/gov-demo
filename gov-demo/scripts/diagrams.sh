#!/usr/bin/env bash
# Re-render every *.mmd under docs/diagrams (here and at the repo root) to PNG.
# Needs Node and Google Chrome. Override the browser path with CHROME=/path/to/chrome.
set -euo pipefail
cd "$(dirname "$0")/.."
export PUPPETEER_SKIP_DOWNLOAD=1
export PUPPETEER_EXECUTABLE_PATH="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
for f in docs/diagrams/*.mmd ../docs/diagrams/*.mmd; do
  [ -f "$f" ] || continue
  npx -y -p @mermaid-js/mermaid-cli mmdc -i "$f" -o "${f%.mmd}.png" -s 2 -b white
done
