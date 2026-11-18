#!/usr/bin/env bash
# Exercise the real React routes using the same Chromium installed for the Python browser gates.
set -euo pipefail
cd "$(dirname "$0")/../apps/web"
export PLAYWRIGHT_NODE_PACKAGE
PLAYWRIGHT_NODE_PACKAGE="$(python -c 'from pathlib import Path; import playwright; print(Path(playwright.__file__).parent / "driver" / "package")')"
export CLUE_TEST_BASE_URL=http://127.0.0.1:5198
export CLUE_ROUTING_TEST_BASE_URL="$CLUE_TEST_BASE_URL"
export CLUE_ROUTING_BROWSER_CHANNEL=chromium
export PLAYWRIGHT_BROWSER_CHANNEL=chromium

node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5198 --strictPort &
vite_pid=$!
trap 'kill "$vite_pid" 2>/dev/null || true' EXIT
curl --fail --silent --retry-connrefused --retry 12 --retry-delay 1 "$CLUE_TEST_BASE_URL" >/dev/null

node --experimental-strip-types --test tests/clueAppointment.test.ts tests/clueRoutingDraft.test.mjs \
  tests/clueEngine115.browser.test.mjs tests/clueRoutingProducts.browser.test.mjs
