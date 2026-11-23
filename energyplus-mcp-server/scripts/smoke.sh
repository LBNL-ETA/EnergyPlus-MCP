#!/usr/bin/env bash
# Post-deploy smoke check.
# Usage: SVC_URL=https://... TOKEN=... ./scripts/smoke.sh

set -euo pipefail

SVC_URL="${SVC_URL:?SVC_URL required (e.g. https://energyplus-mcp-xxx-uw.a.run.app)}"
TOKEN="${TOKEN:?TOKEN required (a bearer token from MCP_TOKENS)}"

echo "==> /health (expect 200)"
code="$(curl -s -o /dev/null -w '%{http_code}' "${SVC_URL}/health")"
[[ "${code}" == "200" ]] || { echo "FAIL: expected 200, got ${code}"; exit 1; }
echo "PASS: ${code}"

echo "==> /mcp without auth (expect 401)"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${SVC_URL}/mcp")"
[[ "${code}" == "401" ]] || { echo "FAIL: expected 401, got ${code}"; exit 1; }
echo "PASS: ${code}"

echo "==> /mcp with bad token (expect 401)"
code="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer obviously-wrong" \
    -X POST "${SVC_URL}/mcp")"
[[ "${code}" == "401" ]] || { echo "FAIL: expected 401, got ${code}"; exit 1; }
echo "PASS: ${code}"

echo "==> /mcp with valid token (expect not-401)"
code="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" \
    -X POST "${SVC_URL}/mcp")"
[[ "${code}" != "401" ]] || { echo "FAIL: got 401 with valid token"; exit 1; }
[[ "${code}" != 5* ]] || { echo "FAIL: server error ${code} with valid token (likely lifespan / startup issue)"; exit 1; }
echo "PASS: ${code} (auth accepted, no 5xx)"

echo "==> /files link routes without auth (expect 404 for an unknown code, not 401)"
code="$(curl -s -o /dev/null -w '%{http_code}' "${SVC_URL}/files/upload/not-a-real-code")"
[[ "${code}" == "404" ]] || { echo "FAIL: expected 404, got ${code}"; exit 1; }
echo "PASS: ${code}"

echo "==> All smoke checks passed."
